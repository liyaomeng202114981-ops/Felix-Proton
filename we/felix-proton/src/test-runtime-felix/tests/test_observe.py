# SPDX-License-Identifier: BSD-3-Clause
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import observe


class ObserverChecks(unittest.TestCase):
    def test_two_processes_share_one_session_and_keep_exit_code(self):
        # Use a private state tree and ignored helper argv. A unique dummy prefix
        # prevents this test from ever joining an existing wrapper namespace.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            prefix = base / 'fixture'
            prefix.mkdir()
            with patch.dict(os.environ, {'XDG_STATE_HOME':str(base/'state'), 'HOME':str(base)}):
                environ = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
                common = [sys.executable, '-B', observe.__file__, 'exec', '--prefix', str(prefix)]
                script = ("import sys; print('trace:wintun:WintunCreateAdapter PRIVATE-test-only'); "
                          "print('PRIVATE-test-only https://invalid.example/'); sys.exit(7)")
                p = subprocess.Popen(common + ['--action','uu','--',sys.executable,'-c',script],env=environ)
                q = subprocess.Popen(common + ['--action','steam','--','/bin/true'],env=environ)
                self.assertEqual(p.wait(timeout=12), 7)
                self.assertEqual(q.wait(timeout=12), 0)
                root = observe.store_for(prefix)
                self.assertEqual(len(list(root.glob('run-*'))),1)
                folder = observe.current(root)
                text = (folder / 'events.jsonl').read_text()
                rows = [json.loads(line) for line in text.splitlines()]
                self.assertNotIn('PRIVATE', text)
                self.assertNotIn('invalid.example', text)
                self.assertEqual((folder / 'events.jsonl').stat().st_mode & 0o777, 0o600)
                self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
                self.assertEqual(sum(r['type']=='observer_started' for r in rows),1)
                self.assertIn('wintun_create_adapter_call',{r['type'] for r in rows})
                self.assertEqual({r['action']:r['exit_code'] for r in rows if r['type']=='launcher_exit'},
                                 {'uu':7,'steam':0})

    def test_steam_tail_ignores_history_and_host_game_records(self):
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ,{'HOME':t}):
            log = Path(t)/'.steam/root/logs/gameprocess_log.txt'
            log.parent.mkdir(parents=True)
            log.write_bytes(b'AppID 1 adding PID 11 as a tracked process\n')
            tail = observe.SteamTail()
            self.assertEqual(tail.poll(True),[])
            with log.open('ab') as f:
                f.write(b'AppID 2 adding PID 12 as a tracked process\n')
            self.assertEqual(tail.poll(False),[])
            with log.open('ab') as f:
                f.write(b'AppID 3 adding PID 42 as a tracked process /PRIVATE/path\n')
            self.assertEqual(tail.poll(True),[{'type':'steam_game_process','appid':3,'change':'added','count':1}])
            log.write_bytes(b'AppID 3 no longer tracking PID 42, exit code -1\n')
            self.assertEqual(tail.poll(True)[0]['exit_code'],-1)

    def test_disk_failure_after_spawn_preserves_child_status(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            with patch.object(observe,'ensure_monitor',return_value=(folder,(folder/'lease').open('a'))), \
                 patch.object(observe,'append',side_effect=[None, OSError('disk full'), OSError('disk full')]), \
                 patch('sys.stderr'):
                rc = observe.run_action(folder,'uu',[sys.executable,'-c',
                    "import sys;print('trace:wintun:WintunCreateAdapter');sys.exit(9)"])
            self.assertEqual(rc,9)

    def test_rotation(self):
        with tempfile.TemporaryDirectory() as t, patch.object(observe,'MAX_LOG',1):
            for n in range(6):
                observe.append(Path(t), {'type':'test','n':n})
            files = list(Path(t).glob('events*.jsonl'))
            self.assertEqual(len(files),3)
            self.assertEqual(sorted(json.loads(p.read_text())['n'] for p in files),[3,4,5])


if __name__ == '__main__':
    unittest.main()
