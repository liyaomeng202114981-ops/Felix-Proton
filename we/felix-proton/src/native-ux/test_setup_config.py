# SPDX-License-Identifier: BSD-3-Clause
"""Prefix/config lifecycle tests. All paths and executable fixtures are temporary."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/"felix-portable-onboard"))
sys.path.insert(0, str(HERE))
import setup_config as sc


class SetupConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.enterContext(mock.patch.dict(os.environ, {"XDG_CONFIG_HOME":str(self.home/".config")}))
        steam_root = self.home/".steam/debian-installation"
        (steam_root/"steamapps").mkdir(parents=True)
        (steam_root/"steam.sh").touch()
        self.runner = steam_root/"compatibilitytools.d"/sc.bootstrap.TOOL/"proton"
        self.runner.parent.mkdir(parents=True)
        self.runner.write_bytes(b"runner fixture")
        self.runner.chmod(0o755)
        self.enterContext(mock.patch.object(sc, "IDENTITY", {"proton":hashlib.sha256(b"runner fixture").hexdigest()}))
        wrap, steam = [self.home/k for k in ("wrapper","native-steam")]
        for tool in (wrap, steam):
            tool.write_text("#!/bin/sh\nexit 88\n")
            tool.chmod(0o755)
        self.valid = {"ready":True,"issues":[],"runner":str(self.runner),"wrapper":str(wrap),
                      "steam_real":str(steam),"pasta_bin_dir":str(self.home/"pasta-bin")}
        self.prepare = self.enterContext(mock.patch.object(sc.bootstrap, "prepare", return_value=self.valid))
        self.discover = self.enterContext(mock.patch.object(sc.bootstrap, "discover", return_value=self.valid))
        self.arc = self.home/"test.1.tar.zst"
        self.prefix = self.home/"Games"/("Felix-UU-"+sc.VERSION)
        self.config = self.home/".config/felix-uu-test"/sc.VERSION/"config.json"

    def test_fresh_creates_only_configuration_and_private_prefix(self):
        self.assertEqual(self.config, sc.ensure_config(self.arc, home=self.home))
        self.prepare.assert_called_once()
        self.assertEqual(self.prefix.lstat().st_mode & 0o777, 0o700)
        self.assertEqual(self.config.lstat().st_mode & 0o777, 0o600)
        self.assertEqual({p.name for p in self.prefix.iterdir()},{".shorin-proton-wrapper.conf",".felix-uu-test-owner"})
        self.assertFalse(list(self.home.rglob("*.desktop")))
        self.assertFalse((self.prefix/"pfx").exists())
        self.assertEqual((self.prefix/".shorin-proton-wrapper.conf").read_text(),"netns=1\n")

    def test_existing_beta_preserves_config_and_user_content(self):
        sc.ensure_config(self.arc, home=self.home)
        data=json.loads(self.config.read_bytes())
        data['desktop_wrapper']=data['wrapper']
        self.config.write_text(json.dumps(data))
        manifest=self.config.with_name("owned-files.json")
        manifest.write_text(json.dumps({"owner":sc.OWNER,"files":{}}))
        manifest.chmod(0o600)
        (self.prefix/"pfx").mkdir()
        sentinel=self.prefix/"pfx/untouched"
        sentinel.write_text("fixture user state")
        before = {x:x.read_bytes() for x in (self.config,manifest,sentinel)}
        self.assertEqual(self.config, sc.ensure_config(home=self.home))
        self.assertEqual(before,{x:x.read_bytes() for x in before})
        self.prepare.assert_called_once()
        self.discover.assert_called_once()

    def test_refuse_existing_unowned_paths_before_extract(self):
        self.prefix.mkdir(parents=True)
        (self.prefix/"existing").touch()
        with self.assertRaises(sc.SetupError): sc.ensure_config(self.arc, home=self.home)
        self.assertTrue((self.prefix/"existing").exists())
        self.assertFalse(self.config.exists())
        self.prepare.assert_not_called()

    def test_foreign_config_and_bad_runner_refused_without_launch(self):
        sc.ensure_config(self.arc, home=self.home)
        original=self.config.read_text()
        cfg=json.loads(original)
        cfg["prefix"]=str(self.home/"Games/other")
        self.config.write_text(json.dumps(cfg))
        with self.assertRaises(sc.SetupError): sc.ensure_config(home=self.home)
        self.discover.assert_not_called()
        self.config.write_text(original)
        self.runner.write_bytes(b"unrecognized runner")
        with self.assertRaises(sc.SetupError): sc.ensure_config(home=self.home)
        self.discover.assert_not_called()

    def test_marker_netns_symlink_absence_never_resets(self):
        sc.ensure_config(self.arc, home=self.home)
        (self.prefix/"pfx").symlink_to(self.home)
        with self.assertRaises(sc.SetupError): sc.ensure_config(home=self.home)
        (self.prefix/"pfx").unlink()
        marker=self.prefix/".shorin-proton-wrapper.conf"
        marker.write_text("netns=1\nnetns=0\n")
        with self.assertRaises(sc.SetupError): sc.ensure_config(home=self.home)
        self.assertEqual(marker.read_text(),"netns=1\nnetns=0\n")
        marker.write_text("netns=1\n")
        (self.prefix/".felix-uu-test-owner").unlink()
        with self.assertRaises(sc.SetupError): sc.ensure_config(home=self.home)

    def test_repair_our_interrupted_creation_only(self):
        real=sc._publish_directory
        def interrupt(path,files):
            if path == self.prefix:
                raise OSError("injected")
            real(path,files)
        with mock.patch.object(sc,"_publish_directory",side_effect=interrupt):
            with self.assertRaises(sc.SetupError):sc.ensure_config(self.arc,home=self.home)
        self.assertTrue(self.config.with_name(sc.PENDING).exists())
        self.assertFalse(self.prefix.exists())
        self.assertEqual(sc.ensure_config(home=self.home),self.config)
        self.assertFalse(self.config.with_name(sc.PENDING).exists())

    def test_missing_archive_does_not_create_configuration(self):
        with self.assertRaises(sc.SetupError):sc.ensure_config(home=self.home)
        self.assertFalse(self.config.exists())
        self.prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
