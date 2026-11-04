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
    def test_removes_expired_set_and_rolls_back_on_exit(self):
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
            class Resolver:
                def __init__(self,*a,**kw):self.i=0
                def poll(self,**kw):
                    self.i+=1
                    return {('1.1.1.1',443)} if self.i==1 else set()
                def status(self):return {'directory':'ok'}
                def close(self):pass
            count=0
            def sleep(_):
                nonlocal count
                count+=1
                if count>=2:cm_guard.STOP=True
            with patch.object(routes,'load',return_value=ctx), \
                 patch.object(cm_guard,'_paths',return_value=(runtime,state)), \
                 patch.object(cm_guard,'_keeper',return_value=(Path('/proc')/str(os.getpid()),123,'net:[42]')), \
                 patch.object(cm_guard,'_live',return_value=[]), \
                 patch.object(policy,'Policy',FakePolicy),patch.object(endpoints,'CMEndpoints',Resolver), \
                 patch.object(cm_guard.time,'sleep',side_effect=sleep),patch.object(cm_guard,'STOP',False):
                cm_guard.serve(ctx.config)
            self.assertEqual(calls,[{('1.1.1.1',443)},set(),'rollback'])
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
