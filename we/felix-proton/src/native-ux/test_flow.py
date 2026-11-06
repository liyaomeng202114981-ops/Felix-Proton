# SPDX-License-Identifier: BSD-3-Clause
"""Black-box dispatcher checks using only temporary files and fixture programs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROUTES = Path(__file__).resolve().with_name('routes.py')
# Dispatcher uses the existing local-beta preflight. Its Linux observations
# are fixture data here; the lower portable Steam gate can independently refuse.
PREFLIGHT = """
import json
from pathlib import Path

class Refused(RuntimeError):
    pass

def session_state(beta, *args, **kwargs):
    return json.loads((Path(beta.prefix).parent / 'preflight.json').read_text())
"""
OBSERVER = """
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
if args[0] != 'exec' or '--' not in args:
    sys.exit('unexpected observer invocation')
root = pathlib.Path(os.environ['CASE_ROOT'])
with (root/'actions').open('a') as out:
    out.write(json.dumps(args[args.index('--action') + 1]) + '\\n')
sys.exit(subprocess.call(args[args.index('--') + 1:]))
"""
LAUNCHER = """#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['CASE_ROOT'])
kind = pathlib.Path(sys.argv[0]).name
record = {'kind':kind,'argv':sys.argv[1:],'config':os.environ.get('UU_NETWORK_CONFIG'),
          'WINEPREFIX':os.environ.get('WINEPREFIX'),'SteamAppId':os.environ.get('SteamAppId'),
          'fsync':os.environ.get('PROTON_NO_FSYNC')}
with (root/'calls').open('a') as out:
    out.write(json.dumps(record) + '\\n')
if kind == 'uu-network-steam' and (root/'lower-gate-refuses').exists():
    sys.exit(2)
with (root/'forwarded').open('a') as out:
    out.write(json.dumps([kind,*sys.argv[1:]]) + '\\n')
"""


class DispatcherFlowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='dispatcher test ')))
        self.home = self.root/'home'
        self.config_dir = self.home/'config'
        self.prefix = self.root/'dedicated UU prefix'
        self.runner = self.root/'runner'/'proton'
        self.felix = self.runner.parent/'felix'
        self.config_dir.mkdir(parents=True)
        (self.felix/'launchers').mkdir(parents=True)
        self.runner.write_text('#!/bin/sh\nexit 99\n')
        self.runner.chmod(0o755)
        (self.felix/'local-beta.py').write_text(PREFLIGHT)
        (self.felix/'observe.py').write_text(OBSERVER)
        (self.felix/'observe.py').chmod(0o755)
        for name in ('uu-network-launch','uu-network-steam'):
            path = self.felix/'launchers'/name
            path.write_text(LAUNCHER)
            path.chmod(0o755)
        uu = self.prefix/'pfx/drive_c/Program Files (x86)/Netease/UU/uu_launcher.exe'
        uu.parent.mkdir(parents=True)
        uu.write_bytes(b'MZ fixture')
        (self.prefix/'.shorin-proton-wrapper.conf').write_text('netns=1\n')
        self.config = self.config_dir/'chosen config.json'
        self.config.write_text(json.dumps({'prefix':str(self.prefix),'runner':str(self.runner)}))
        source = self.config_dir/'felix-native-ux'/'active.json'
        source.parent.mkdir(); source.write_text(json.dumps({'config':str(self.config)}))
        self.base_state = dict(beta_network=None,beta_uu=False,native_steam_count=0,conflict=None,reason=None,
                               client_installed=True)
        self.set_state()
        # Only the fixture subprocess receives this private home and XDG tree.
        self.env = dict(HOME=str(self.home), XDG_CONFIG_HOME=str(self.config_dir),
                        XDG_DATA_HOME=str(self.home/'data'),XDG_RUNTIME_DIR=str(self.home/'runtime'),
                        PATH='/usr/bin:/bin', LC_ALL='C.UTF-8', FELIX_STEAM_CM_GUARD='0', PYTHONDONTWRITEBYTECODE='1',
                        CASE_ROOT=str(self.root), DBUS_SESSION_BUS_ADDRESS='unix:path='+str(self.root/'no-bus'))
        Path(self.env['XDG_RUNTIME_DIR']).mkdir(mode=0o700)

    def set_state(self, **changes):
        (self.root/'preflight.json').write_text(json.dumps(self.base_state | changes))

    def run_route(self, action, *arguments, env=None):
        return subprocess.run([sys.executable,'-B',str(ROUTES),action,*arguments],
                              cwd=self.root,env=self.env | (env or {}),text=True,capture_output=True,timeout=6)

    def rows(self, name):
        path = self.root/name
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def test_steam_first_before_uu_and_game_parameters_survive(self):
        args=['steam://rungameid/123','--','', 'two words', '"quote"', '$USER;$(echo surprise)', '中文']
        res = self.run_route('steam', *args, env={'WINEPREFIX':'/fixture/original','SteamAppId':'123'})
        self.assertEqual(res.returncode,0,res.stderr)
        self.assertEqual(self.rows('actions'), ['steam'])
        self.assertEqual(self.rows('forwarded'), [['uu-network-steam', *args]])
        call = self.rows('calls')[0]
        self.assertEqual(call['config'], str(self.config))
        self.assertEqual((call['WINEPREFIX'],call['SteamAppId'],call['fsync']), ('/fixture/original','123',None))
        # A later UU launch is independent of the first Steam/game request.
        self.set_state(beta_network='net:[77]', native_steam_count=1)
        res=self.run_route('uu')
        self.assertEqual(res.returncode,0,res.stderr)
        self.assertEqual(self.rows('actions'), ['steam','uu'])
        self.assertEqual(self.rows('forwarded')[-1][0], 'uu-network-launch')

    def test_uu_first_does_not_start_steam(self):
        res=self.run_route('uu')
        self.assertEqual(res.returncode,0,res.stderr)
        self.assertEqual(self.rows('actions'), ['uu'])
        self.assertEqual([row['kind'] for row in self.rows('calls')], ['uu-network-launch'])

    def test_existing_same_network_client_receives_every_uri(self):
        self.set_state(beta_network='net:[77]', beta_uu=True, native_steam_count=1)
        for uri in ('steam://open/library', 'steam://rungameid/42'):
            res=self.run_route('steam',uri)
            self.assertEqual(res.returncode,0,res.stderr)
        self.assertEqual(self.rows('forwarded'), [
            ['uu-network-steam','steam://open/library'],['uu-network-steam','steam://rungameid/42']])

    def test_ordinary_warm_click_requests_library_without_an_existing_window(self):
        self.set_state(beta_network='net:[77]', beta_uu=True, native_steam_count=1)
        res=self.run_route('steam',env={'DISPLAY':''})
        self.assertEqual(res.returncode,0,res.stderr)
        self.assertEqual(self.rows('forwarded'),[['uu-network-steam','steam://open/games']])
        self.assertEqual(self.rows('actions'),['steam'])

    def test_cold_and_silent_launch_preserve_arguments(self):
        res=self.run_route('steam')
        self.assertEqual(res.returncode,0,res.stderr)
        self.set_state(beta_network='net:[77]', beta_uu=True, native_steam_count=1)
        res=self.run_route('steam','-silent')
        self.assertEqual(res.returncode,0,res.stderr)
        self.assertEqual(self.rows('forwarded'),[['uu-network-steam'],['uu-network-steam','-silent']])

    def test_host_steam_refused_before_uu_or_steam_is_forwarded(self):
        self.set_state(native_steam_count=1, conflict='Steam 已在其他网络', reason='wrong-network')
        for action in ('steam','uu'):
            self.assertNotEqual(self.run_route(action).returncode,0)
        self.assertEqual(self.rows('forwarded'),[])

    def test_steam_gate_can_refuse_after_preflight_race(self):
        (self.root/'lower-gate-refuses').touch()
        res=self.run_route('steam','steam://open/library')
        self.assertEqual(res.returncode,2,res.stderr)
        self.assertEqual([r['kind'] for r in self.rows('calls')], ['uu-network-steam'])
        self.assertEqual(self.rows('forwarded'),[])


if __name__=='__main__':
    unittest.main()
