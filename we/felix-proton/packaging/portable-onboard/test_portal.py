# SPDX-License-Identifier: BSD-3-Clause
import os
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import start


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.home=Path(self.enterContext(tempfile.TemporaryDirectory()))/'名字 test'
        self.home.mkdir()
        self.enterContext(patch.dict(os.environ,{'HOME':str(self.home),'XDG_DATA_HOME':str(self.home/'data'),
                       'XDG_CONFIG_HOME':str(self.home/'config'),'DISPLAY':'','WAYLAND_DISPLAY':''}))
        self.steam_root=self.home/'other/Steam'
        tool=self.steam_root/'compatibilitytools.d'/start.bootstrap.TOOL
        for n in ('proton','felix/launchers/uu-network-launch','felix/launchers/uu-network-steam',
                  'felix/launchers/uu_network.py','felix/observe.py'):
            p=tool/n
            p.parent.mkdir(parents=True,exist_ok=True)
            p.touch(); p.chmod(0o700)
        self.report={'steam_root':str(self.steam_root),'steam_real':'/usr/bin/steam',
                     'wrapper':'/opt/mock/shorin-proton-wrapper','pasta_bin_dir':'/opt/mock',
                     'uu_installer':None,'uu_installer_sha256':None}
        self.enterContext(patch.object(start.bootstrap,'prepare',return_value=self.report))
        self.args=SimpleNamespace(archive=self.home/'fixture',uu_installer=None)
        self.args.archive.touch()
        self.apps=self.home/'data/applications'
        self.apps.mkdir(parents=True)
        (self.apps/'steam.desktop').write_text('original')

    def test_install_repeat_open_remove_and_keep_real_steam_entry(self):
        start.install(self.args)
        start.install(self.args)
        files=sorted(x.name for x in self.apps.glob('*.desktop'))
        self.assertEqual(files,['felix-uu-portal-preview1.desktop','steam.desktop'])
        self.assertIn(str(start.libdir()/'start.py'),(self.apps/files[0]).read_text())
        self.assertTrue((start.libdir()/'start.py').exists())
        cfg=json.loads((start.cfgdir()/'config.json').read_text())
        self.assertEqual(cfg['wrapper'],self.report['wrapper'])
        self.assertTrue(cfg['runner'].startswith(str(self.steam_root)))
        with patch.object(start,'launch_pair',return_value='ok') as launch:
            self.assertEqual(start.main(['open']),0)
            self.assertEqual(launch.call_args[0][0].read_config(),cfg)
        self.assertEqual(start.main(['remove']),0)
        self.assertEqual((self.apps/'steam.desktop').read_text(),'original')
        self.assertFalse((self.apps/files[0]).exists())
        self.assertTrue(Path(cfg['prefix']).is_dir())

    def test_foreign_desktop_entry_preserved(self):
        dst=self.apps/'felix-uu-portal-preview1.desktop'
        dst.write_text('mine')
        with self.assertRaises(start.Refused):start.install(self.args)
        self.assertEqual(dst.read_text(),'mine')
        self.assertFalse((start.cfgdir()/'paths.json').exists())
