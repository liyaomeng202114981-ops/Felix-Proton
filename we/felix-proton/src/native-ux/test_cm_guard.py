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
    def test_notifies_once_after_recovery_and_removes_expired_rules(self):
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
            polls=iter([set(),set(),peer,peer,set(),peer])
            class Resolver:
                def __init__(self,*a,**kw):pass
                def poll(self,**kw):return next(polls)
                def status(self):return {'directory':'ok'}
                def close(self):pass
            states=[]
            def sleep(_):
                states.append(json.loads((runtime/'status.json').read_text())['state'])
                if len(states)==6:cm_guard.STOP=True
            def notify(*args,**kwargs):
                meta=json.loads((runtime/'status.json').read_text())
                self.assertEqual((meta['state'],meta['rules']),('ready',1))
                raise cm_guard.subprocess.TimeoutExpired(args[0],kwargs['timeout'])
            with patch.object(routes,'load',return_value=ctx), \
                 patch.object(cm_guard,'_paths',return_value=(runtime,state)), \
                 patch.object(cm_guard,'_keeper',return_value=(Path('/proc')/str(os.getpid()),123,'net:[42]')), \
                 patch.object(cm_guard,'_live',return_value=[]), \
                 patch.object(policy,'Policy',FakePolicy),patch.object(endpoints,'CMEndpoints',Resolver), \
                 patch.object(cm_guard.time,'monotonic',side_effect=lambda:6*len(states)), \
                 patch.object(cm_guard.subprocess,'run',side_effect=notify) as send, \
                 patch.object(cm_guard.time,'sleep',side_effect=sleep),patch.object(cm_guard,'STOP',False):
                cm_guard.serve(ctx.config)
            send.assert_called_once_with(['notify-send','Steam 连接保护','连接保护已就绪。'],
                                         stdout=cm_guard.subprocess.DEVNULL,stderr=cm_guard.subprocess.DEVNULL,
                                         timeout=2,check=False)
            self.assertEqual(states,['preparing','error','ready','ready','error','ready'])
            self.assertEqual(calls,[peer,set(),peer,'rollback'])
            meta=json.loads((runtime/'status.json').read_text())
            self.assertEqual(meta['namespace'],'net:[42]')
            self.assertEqual(meta['state'],'stopped')

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
                def poll(self,**kw):raise OSError('fixture')
                def close(self):pass
            with patch.object(routes,'load',return_value=ctx), \
                 patch.object(cm_guard,'_paths',return_value=(d/'rt',d/'state')), \
                 patch.object(cm_guard,'_keeper',return_value=(Path('/proc')/str(os.getpid()),123,'net:[42]')), \
                 patch.object(cm_guard,'_live',return_value=[]), \
                 patch.object(policy,'Policy',FakePolicy),patch.object(endpoints,'CMEndpoints',Resolver), \
                 patch.object(cm_guard,'STOP',False):
                cm_guard.serve(ctx.config)
            self.assertEqual(done,[True])
            self.assertEqual(json.loads((d/'rt/status.json').read_text())['state'],'error')

    def test_default_preparation_and_explicit_optout(self):
        with patch.dict(os.environ,{},clear=True),patch.object(cm_guard,'ensure') as prepare:
            routes.prime_control_route(object())
            prepare.assert_called_once()
        with patch.dict(os.environ,{'FELIX_STEAM_CM_GUARD':'0'}),patch.object(cm_guard,'ensure') as prepare:
            routes.prime_control_route(object())
            prepare.assert_not_called()


if __name__=='__main__':unittest.main()
