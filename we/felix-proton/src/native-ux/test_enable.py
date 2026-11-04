# SPDX-License-Identifier: BSD-3-Clause
import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import enable


class OrdinaryEntries(unittest.TestCase):
    def setUp(self):
        self.tmp=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home=self.tmp/'home 中文'
        self.home.mkdir()
        self.enterContext(patch.dict(os.environ,{
            'HOME':str(self.home),'XDG_DATA_HOME':str(self.home/'data'),'XDG_STATE_HOME':str(self.home/'state'),
            'XDG_CONFIG_HOME':str(self.home/'config'),'XDG_DATA_DIRS':str(self.tmp/'system'),
            'DISPLAY':'','WAYLAND_DISPLAY':''}))
        self.apps=self.tmp/'system/applications';self.apps.mkdir(parents=True)
        (self.apps/'steam.desktop').write_text('[Desktop Entry]\nType=Application\nName=Steam\nExec=/usr/bin/steam %U\nIcon=steam\n')
        self.prefix=self.home/'Games/Test'; self.client=self.prefix/'pfx/drive_c/Program Files (x86)/Netease/UU/uu_launcher.exe'
        self.config=self.home/'preexisting.json'
        self.config.write_text(json.dumps({'prefix':str(self.prefix),'runner':str(self.home/'runner/proton')}))
        self.enterContext(patch.object(enable.setup_config,'ensure_config',return_value=self.config))
        self.args=SimpleNamespace(archive=None,uu_installer=None)
        self.dest=self.home/'data/applications'

    def test_uninitialized_prefix_cannot_take_over_steam(self):
        self.enterContext(patch.object(enable.routes,'state',return_value={}))
        self.enterContext(patch.object(enable,'select_installer',side_effect=RuntimeError('cancelled')))
        with self.assertRaises(RuntimeError):
            enable.enable(self.args)
        self.assertFalse((self.dest/'steam.desktop').exists())
        self.assertFalse(enable.routes.active_file().exists())

    def test_upgrade_only_replaces_a_known_previous_helper(self):
        target=self.tmp/'routes.py'
        target.write_bytes(b'previous')
        previous=hashlib.sha256(b'previous').hexdigest()
        enable.stage_file(target,b'new',previous)
        self.assertEqual(target.read_bytes(),b'new')
        target.write_bytes(b'edited')
        with self.assertRaises(RuntimeError):
            enable.stage_file(target,b'new',previous)
        self.assertEqual(target.read_bytes(),b'edited')

    def test_ready_machine_uses_existing_prefix_and_can_restore(self):
        self.client.parent.mkdir(parents=True); self.client.write_bytes(b'MZ')
        (self.prefix/'pfx/system.reg').touch()
        with patch.object(enable.subprocess,'Popen',side_effect=AssertionError('no applications should start')):
            enable.enable(self.args)
            enable.enable(self.args)
        self.assertEqual(enable.routes.load().config,self.config)
        self.assertEqual(sorted(p.name for p in self.dest.glob('*.desktop')),['steam.desktop','uu-accelerator.desktop'])
        self.assertIn(' steam %U',(self.dest/'steam.desktop').read_text())
        self.assertIn(' uu\n',(self.dest/'uu-accelerator.desktop').read_text())
        enable.desktop.restore(enable.statedir())
        self.assertFalse((self.dest/'steam.desktop').exists())
        self.assertTrue(self.client.exists())
