# SPDX-License-Identifier: BSD-3-Clause
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import cm_guard
import endpoints
import policy
import routes


class ControllerTests(unittest.TestCase):
    def test_notifies_once_and_stops_when_keeper_disappears(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);runtime=d/'rt';state=d/'state'
            ctx=SimpleNamespace(prefix=d/'prefix',config=d/'config',root=d)
            calls=[]
            class FakePolicy:
                def __init__(self,u,n,path):self.path=path
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def capture_baseline(self):
                    self.path.write_text(json.dumps({'baseline':{'source':'192.0.2.1'}}))
                def reconcile(self,targets):
                    calls.append(set(targets));return {'rules':len(targets)}
                def rollback(self):calls.append('rollback')
            peer={('1.1.1.1',443)}
            polls=iter([set(),peer,set(),peer,peer,peer,set(),peer])
            class Resolver:
                def __init__(self,*a,**kw):pass
                def poll(self,**kw):return next(polls)
                def status(self):return {'directory':'ok'}
                def wait_for_results(self,delay):
                    early_waits.append(delay)
                    sleep(delay)
                def close(self):pass
            states=[]
            updated=[]
            early_waits=[]
            clock=[0,3,6,8,10,14,16,18,20]
            def now():
                return clock[len(states)]
            def sleep(_):
                meta=json.loads((runtime/'status.json').read_text())
                states.append(meta['state'])
                updated.append(meta['updated'])
            def keeper(_):
                if len(states)==8:
                    raise FileNotFoundError('keeper fixture')
                return Path('/proc')/str(os.getpid()),123,'net:[42]'
            def notify(*args,**kwargs):
                meta=json.loads((runtime/'status.json').read_text())
                self.assertEqual((meta['state'],meta['rules']),('ready',1))
                raise cm_guard.subprocess.TimeoutExpired(args[0],kwargs['timeout'])
            with patch.object(routes,'load',return_value=ctx), \
                 patch.object(cm_guard,'_paths',return_value=(runtime,state)), \
                 patch.object(cm_guard,'_keeper',side_effect=keeper), \
                 patch.object(cm_guard,'_live',return_value=[]), \
                 patch.object(policy,'Policy',FakePolicy),patch.object(endpoints,'CMEndpoints',Resolver), \
                 patch.object(cm_guard.time,'monotonic',side_effect=now), \
                 patch.object(cm_guard.time,'time',side_effect=now), \
                 patch.object(cm_guard.subprocess,'run',side_effect=notify) as send, \
                 patch.object(cm_guard.time,'sleep',side_effect=sleep),patch.object(cm_guard,'STOP',False):
                cm_guard.serve(ctx.config)
            send.assert_called_once_with(['notify-send','Steam 连接保护','连接保护已就绪。'],
                                         stdout=cm_guard.subprocess.DEVNULL,stderr=cm_guard.subprocess.DEVNULL,
                                         timeout=2,check=False)
            self.assertEqual(states,['preparing','preparing','error','ready','ready','ready','error','ready'])
            self.assertEqual(updated,[0,0,6,8,8,14,16,18])
            self.assertEqual(early_waits,[.4,.4])
            self.assertEqual(calls,[peer,set(),peer,set(),peer,'rollback'])
            meta=json.loads((runtime/'status.json').read_text())
            self.assertEqual(meta['namespace'],'net:[42]')
            self.assertEqual(meta['state'],'stopped')
            events=[json.loads(line)['type'] for line in (state/'events.jsonl').read_text().splitlines()]
            self.assertNotIn('guard_error',events)
            self.assertEqual(events[-2:],['rules_removed','guard_stopped'])

    def test_rolls_back_on_lookup_failure(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);ctx=SimpleNamespace(prefix=d,config=d/'config',root=d)
            done=[]
            class FakePolicy:
                def __init__(self,u,n,path):self.path=path
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def capture_baseline(self):self.path.write_text(json.dumps({'baseline':{'source':'192.0.2.1'}}))
                def rollback(self):done.append(True)
            class Resolver:
                def __init__(self,*a,**kw):pass
                def poll(self,**kw):raise FileNotFoundError('resolver fixture')
                def close(self):pass
            with patch.object(routes,'load',return_value=ctx), \
                 patch.object(cm_guard,'_paths',return_value=(d/'rt',d/'state')), \
                 patch.object(cm_guard,'_keeper',return_value=(Path('/proc')/str(os.getpid()),123,'net:[42]')), \
                 patch.object(cm_guard,'_live',return_value=[]), \
                 patch.object(policy,'Policy',FakePolicy),patch.object(endpoints,'CMEndpoints',Resolver), \
                 patch.object(cm_guard,'STOP',False):
                cm_guard.serve(ctx.config)
            self.assertEqual(done,[True])
            meta=json.loads((d/'rt/status.json').read_text())
            self.assertEqual((meta['state'],meta['error']),('error','FileNotFoundError'))

    def test_missing_keeper_at_start_is_an_error(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);ctx=SimpleNamespace(prefix=d,config=d/'config',root=d)
            with patch.object(routes,'load',return_value=ctx), \
                 patch.object(cm_guard,'_paths',return_value=(d/'rt',d/'state')), \
                 patch.object(cm_guard,'_keeper',side_effect=FileNotFoundError('keeper fixture')), \
                 patch.object(policy,'Policy') as open_policy:
                cm_guard.serve(ctx.config)
            open_policy.assert_not_called()
            meta=json.loads((d/'rt/status.json').read_text())
            self.assertEqual((meta['state'],meta['error']),('error','FileNotFoundError'))

    def test_default_preparation_and_explicit_optout(self):
        with patch.dict(os.environ,{},clear=True),patch.object(cm_guard,'ensure') as prepare:
            routes.prime_control_route(object())
            prepare.assert_called_once()
        with patch.dict(os.environ,{'FELIX_STEAM_CM_GUARD':'0'}),patch.object(cm_guard,'ensure') as prepare:
            routes.prime_control_route(object())
            prepare.assert_not_called()


class RecoveryTests(unittest.TestCase):
    def run_guard(self, *, failures=None, live=(), stop_after=1):
        """Run the controller clock and policy failure paths without networking."""
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        runtime,state=root/'rt',root/'state'
        ctx=SimpleNamespace(prefix=root/'prefix',config=root/'config',root=root)
        targets={(f'23.40.100.{i}',443) for i in range(1,5)}
        scripts={name:list(values) for name,values in (failures or {}).items()}
        calls=[]
        snapshots=[]
        notices=[]
        now=[0.]
        successes=[0]
        capture_count=[0]
        self.addCleanup(setattr,cm_guard,'STOP',False)

        def attempt(name, targets=None):
            calls.append((name,now[0],targets))
            pending=scripts.get(name,[])
            error=pending.pop(0) if pending else None
            if error:
                raise policy.PolicyError(error)

        class FakePolicy:
            def __init__(self,u,n,path):self.path=path
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def capture_baseline(self):
                attempt('capture')
                capture_count[0]+=1
                self.path.write_text(json.dumps({'baseline':{'source':f'192.0.2.{capture_count[0]}'}}))
            def reconcile(self,targets):
                attempt('reconcile',set(targets))
                successes[0]+=1
                return {'rules':len(targets)}
            def rollback(self):
                attempt('rollback')
                self.path.unlink(missing_ok=True)

        class Resolver:
            def __init__(self,*args,**kwargs):pass
            def poll(self,**kwargs):return targets
            def status(self):return {'directory':'ok'}
            def wait_for_results(self,delay):sleep(delay)
            def close(self):pass

        write=cm_guard._private_file
        def publish(path,data):
            write(path,data)
            snapshots.append(dict(data))
            if data['state']=='ready' and successes[0]>=stop_after:
                cm_guard.STOP=True
        def sleep(delay):
            now[0]+=delay
            if now[0]>90:
                self.fail('controller did not recover within the fixture clock')

        with patch.object(routes,'load',return_value=ctx), \
             patch.object(cm_guard,'_paths',return_value=(runtime,state)), \
             patch.object(cm_guard,'_keeper',return_value=(Path('/proc')/str(os.getpid()),123,'net:[42]')), \
             patch.object(cm_guard,'_live',return_value=list(live)), \
             patch.object(policy,'Policy',FakePolicy),patch.object(endpoints,'CMEndpoints',Resolver), \
             patch.object(cm_guard.time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(cm_guard.time,'time',side_effect=lambda:now[0]), \
             patch.object(cm_guard.time,'sleep',side_effect=sleep), \
             patch.object(cm_guard,'_private_file',side_effect=publish), \
             patch.object(cm_guard,'_notify',side_effect=notices.append), \
             patch.object(cm_guard,'RECHECK_INTERVAL',1),patch.object(cm_guard,'STOP',False):
            cm_guard.serve(ctx.config)
        events=[json.loads(line) for line in (state/'events.jsonl').read_text().splitlines()]
        self.assertEqual(snapshots[-1]['state'],'stopped')
        self.assertNotIn('guard_error',[event['type'] for event in events])
        return SimpleNamespace(calls=calls,snapshots=snapshots,notices=notices,events=events,targets=targets)

    def test_transient_path_errors_recover_without_recapturing_baseline(self):
        for reason in ('netlink_query_failed','earlier_rule_overrides','foreign_rule_conflict'):
            with self.subTest(reason=reason):
                result=self.run_guard(failures={'reconcile':[None,reason,reason,None]},stop_after=2)
                self.assertEqual(sum(name=='capture' for name,_,_ in result.calls),1)
                self.assertEqual(sum(name=='rollback' for name,_,_ in result.calls),1)
                self.assertTrue(any(s['state']=='recovering' and s['error']==reason for s in result.snapshots))
                self.assertEqual(result.notices,[
                    '连接保护已就绪。','连接保护暂不可用，正在自动重试。','连接保护已恢复。'])
                self.assertEqual(sum(e['type']=='recovery_wait' for e in result.events),1)
                self.assertEqual(sum(e['type']=='recovery_succeeded' for e in result.events),1)

    def test_retry_delay_is_bounded_and_initial_recovery_notifies_once(self):
        result=self.run_guard(failures={'reconcile':['netlink_query_failed']*6+[None]})
        attempts=[at for name,at,_ in result.calls if name=='reconcile']
        self.assertEqual([round(b-a,5) for a,b in zip(attempts,attempts[1:])],[1,2,4,8,15,15])
        self.assertEqual(result.notices,['连接保护已就绪。'])
        self.assertEqual(sum(name=='capture' for name,_,_ in result.calls),1)

    def test_anchor_reset_cleans_old_rules_and_waits_for_safe_capture(self):
        result=self.run_guard(failures={
            'reconcile':[None,'uplink_changed',None],
            'capture':[None,'tunnel_active','tunnel_active',None],
        },stop_after=2)
        names=[name for name,_,_ in result.calls]
        self.assertEqual(names,[
            'capture','reconcile','reconcile','rollback','capture','capture','capture','reconcile','rollback'])
        errors=[s['error'] for s in result.snapshots if s['state']=='recovering']
        self.assertIn('uplink_changed',errors)
        self.assertIn('tunnel_active',errors)
        self.assertEqual(result.notices,[
            '连接保护已就绪。','连接保护暂不可用，正在自动重试。','连接保护已恢复。'])

    def test_failed_reset_cleanup_is_retried_before_new_capture(self):
        result=self.run_guard(failures={
            'reconcile':[None,'uplink_default_changed',None],
            'rollback':['recovery_pending',None],
        },stop_after=2)
        names=[name for name,_,_ in result.calls]
        self.assertEqual(names,[
            'capture','reconcile','reconcile','rollback','rollback','capture','reconcile','rollback'])
        self.assertTrue(any(s['state']=='recovering' and s['error']=='recovery_pending' for s in result.snapshots))

    def test_uu_sourced_live_peer_remains_deferred_after_recovery(self):
        peer=('23.40.100.1',443)
        result=self.run_guard(failures={'reconcile':['netlink_change_failed',None]},
                              live=[('198.18.0.2',peer)])
        self.assertTrue(all(peer not in targets for name,_,targets in result.calls if name=='reconcile'))
        ready=[s for s in result.snapshots if s['state']=='ready']
        self.assertTrue(ready)
        self.assertEqual((ready[-1]['rules'],ready[-1]['deferred']),(3,1))
        self.assertEqual(result.notices,['连接保护已就绪。'])


if __name__=='__main__':unittest.main()
