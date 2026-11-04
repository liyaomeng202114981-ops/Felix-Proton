# SPDX-License-Identifier: BSD-3-Clause
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import desktop


def steam(cmd="/usr/bin/steam"):
    return (f"# personal comment\n[Desktop Entry]\nType=Application\nName=Steam\nName[zh_CN]=我的 Steam\n"
            f"Icon=my-icon\nMimeType=x-scheme-handler/steam;x-scheme-handler/steamlink;\n"
            f"Actions=Store;Library;\nExec={cmd} %U\nStartupWMClass=Steam\nX-MySetting=1\n\n"
            f"[Desktop Action Store]\nName=Store\nExec={cmd} steam://store\n\n"
            f"[Desktop Action Library]\nName=Library\nExec={cmd} -silent steam://open/games\n").encode()


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.root / "personal"
        self.apps = self.home / ".local/share/applications"
        self.config = self.home / ".config"
        self.system = self.root / "system/apps"
        self.state = self.root / "private-state"
        self.helper = self.home / "Felix % 指南" / 'start"$here.py'
        self.helper.parent.mkdir(parents=True)
        self.helper.write_text("pass")
        self.apps.mkdir(parents=True)
        self.system.mkdir(parents=True)
        self.config.mkdir(parents=True)
        self.enterContext(mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.apps.parent)}))
        self.steam = self.apps / "steam.desktop"
        self.uu = self.apps / "uu-accelerator.desktop"
        self.auto = self.config / "autostart/steam.desktop"
        (self.system / "steam.desktop").write_bytes(steam())

    def install(self):
        return desktop.install(self.helper, self.state, apps_dir=self.apps, home=self.home,
                               config_home=self.config, system_dirs=[self.system])

    def restore(self):
        return desktop.restore(self.state, apps_dir=self.apps, home=self.home, config_home=self.config)

    def own(self, name, expected=True):
        if name == "steam-uu.desktop":
            data = ("[Desktop Entry]\nType=Application\nName=Steam（UU 加速）\nComment=在网易 UU 的独立网络内启动 Steam\n"
                    f"Exec={self.home}/.local/lib/uu-accelerator/steam %U\nIcon=steam\nTerminal=false\nCategories=Game;\nStartupWMClass=Steam\n")
        else:
            preview = name == desktop._PREVIEW
            script = (self.apps.parent / "felix-uu-portal/preview1/start.py") if preview else (
                self.home / ".local/share/Steam/compatibilitytools.d" / ("felix-proton-uu-test-" + desktop._VERSION) / "felix/local-beta.py")
            mode = "open" if preview else ("uu" if name == desktop._TEST_IDS[0] else "steam")
            data = f"[Desktop Entry]\nType=Application\nName=标记的测试图标\nExec=/usr/bin/python3 {desktop._quote(script)} {mode}\n"
            manifest = self.config / ("felix-uu-portal/preview1" if preview else "felix-uu-test/" + desktop._VERSION) / "owned-files.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            record = json.loads(manifest.read_text()) if manifest.is_file() else {"owner": "Felix UU " + desktop._VERSION,"files": {}}
            record["files"][str(self.apps/name)] = hashlib.sha256(data.encode()).hexdigest() if expected else "0" * 64
            manifest.write_text(json.dumps(record))
        (self.apps/name).write_text(data)
        return (self.apps/name).read_bytes()

    def test_existing_user_desktop_keeps_id_actions_uris_icons_and_bytes_on_restore(self):
        original = steam(str(self.home / ".local/lib/uu-accelerator/steam")).replace(b"\n", b"\r\n")
        self.steam.write_bytes(original)
        self.steam.chmod(0o640)
        os.utime(self.steam, ns=(1700000000000000000,1700000006000123456))
        os.setxattr(self.steam, "user.fixture", b"keep me")
        original_uu = b"[Desktop Entry]\nType=Application\nName=custom\nIcon=my-custom-icon\nExec=old --quiet\nStartupWMClass=uu.exe\n"
        self.uu.write_bytes(original_uu)
        self.install()
        text = self.steam.read_bytes()
        head = ("/usr/bin/python3 " + desktop._quote(self.helper) + " steam").encode()
        self.assertEqual(text, original.replace(os.fsencode(self.home / ".local/lib/uu-accelerator/steam"), head))
        self.assertIn(b"Icon=my-custom-icon", self.uu.read_bytes())
        self.assertNotIn(b"--quiet", self.uu.read_bytes())
        self.assertEqual(self.install()["changed"], [])
        self.restore()
        self.assertEqual(self.steam.read_bytes(), original)
        self.assertEqual(self.steam.stat().st_mode & 0o777,0o640)
        self.assertEqual(self.steam.stat().st_mtime_ns,1700000006000123456)
        self.assertEqual(os.getxattr(self.steam, "user.fixture"), b"keep me")
        self.assertEqual(self.uu.read_bytes(), original_uu)
        self.assertEqual(self.restore()["changed"], [])

    def test_system_copy_new_uu_and_restore_remove_only_user_overrides(self):
        original = steam()
        self.install()
        self.assertEqual((self.system/"steam.desktop").read_bytes(), original)
        self.assertIn("Name=网易 UU 加速器", self.uu.read_text())
        self.assertIn("Exec=/usr/bin/python3 ", self.steam.read_text())
        if shutil.which("desktop-file-validate"):
            for p in [self.uu,self.steam]:
                subprocess.run(["desktop-file-validate",str(p)],check=True, capture_output=True)
        private = self.state / "desktop-backup-v1"
        self.assertEqual(private.stat().st_mode & 0o777,0o700)
        self.assertEqual((private/"state.json").stat().st_mode & 0o777,0o600)
        self.restore()
        self.assertFalse(self.uu.exists())
        self.assertFalse(self.steam.exists())
        self.assertEqual((self.system/"steam.desktop").read_bytes(), original)

    def test_recognized_commands_preserve_exact_argument_tail(self):
        for exe in ["steam", '"/usr/bin/steam"', "/usr/games/steam"]:
            with self.subTest(exe=exe):
                raw = steam(exe).replace((exe+" %U").encode(), (exe+'\t-silent "%u" --long-name=value').encode())
                self.steam.write_bytes(raw)
                self.install()
                self.assertIn(b' steam\t-silent "%u" --long-name=value', self.steam.read_bytes())
                self.restore()
                self.assertEqual(self.steam.read_bytes(), raw)

    def test_unrecognized_main_or_action_and_dbus_activation_are_rejected(self):
        for raw in [steam("env FOO=1 /usr/bin/steam"),steam().replace(b"Exec=/usr/bin/steam steam://store",b"Exec=/opt/unknown store"),
                    steam().replace(b"Type=Application", b"Type=Application\nDBusActivatable=true")]:
            with self.subTest(raw=raw):
                self.steam.write_bytes(raw)
                with self.assertRaises(desktop.DesktopError):
                    self.install()
                self.assertFalse(self.uu.exists())
                self.assertEqual(self.steam.read_bytes(), raw)

    def test_autostart_only_known_steam_with_original_options(self):
        self.auto.parent.mkdir()
        old = steam("/usr/games/steam").replace(b" %U", b" -silent %u")
        self.auto.write_bytes(old)
        font = self.auto.with_name("steam-updater-font.desktop")
        font.write_bytes(b"never touched")
        self.install()
        self.assertIn(b" steam -silent %u", self.auto.read_bytes())
        self.assertEqual(font.read_bytes(), b"never touched")
        self.restore()
        self.assertEqual(self.auto.read_bytes(), old)
        self.auto.write_bytes(steam("/somebody-elses/steam"))
        self.assertIn("autostart/steam.desktop", self.install()["skipped"])
        self.assertEqual(self.auto.read_bytes(), steam("/somebody-elses/steam"))

    def test_known_duplicates_and_preview_hidden_only_when_proven(self):
        names = ["steam-uu.desktop", *desktop._TEST_IDS, desktop._PREVIEW]
        before = {n:self.own(n) for n in names}
        result = self.install()
        self.assertEqual(set(result["hidden"]),set(names))
        for n in names:
            self.assertIn(b"NoDisplay=true", (self.apps/n).read_bytes())
        self.restore()
        for n in names:
            self.assertEqual((self.apps/n).read_bytes(), before[n])

    def test_personalized_duplicates_and_unrelated_desktops_stay_untouched(self):
        self.own("steam-uu.desktop")
        old_alias=self.apps/"steam-uu.desktop"
        old_alias.write_text(old_alias.read_text().replace("Name=Steam", "Name=My private Steam"))
        beta=desktop._TEST_IDS[0]
        self.own(beta,expected=False)
        unrelated=self.apps/"remote-uu-service.desktop"
        unrelated.write_bytes(b"arbitrary content")
        result=self.install()
        self.assertEqual(set(result["skipped"]),{"steam-uu.desktop",beta})
        self.assertNotIn("NoDisplay",old_alias.read_text())
        self.assertNotIn("NoDisplay",(self.apps/beta).read_text())
        self.assertEqual(unrelated.read_bytes(),b"arbitrary content")

    def test_broken_symlink_is_never_adopted(self):
        self.steam.symlink_to("absent")
        with self.assertRaises(desktop.DesktopError):
            self.install()
        self.assertTrue(self.steam.is_symlink())
        self.assertFalse(self.uu.exists())

    def test_interrupted_install_resumes_or_restores_without_foreign_writes(self):
        original = desktop._apply_one
        def fail_on_uu(path,target):
            if path == self.uu: raise OSError("fixture write failure")
            return original(path,target)
        with mock.patch.object(desktop,"_apply_one",side_effect=fail_on_uu), self.assertRaises(desktop.DesktopError):
            self.install()
        self.assertTrue(self.steam.exists())
        self.assertFalse(self.uu.exists())
        self.assertEqual(self.install()["changed"], ["uu-accelerator.desktop"])
        self.restore()
        self.assertFalse(self.steam.exists())
        self.assertFalse(self.uu.exists())

    def test_interrupted_restore_is_retriable_and_preserves_new_user_edits(self):
        self.install()
        original=desktop._apply_one
        def fail_on_uu(path,target):
            if path == self.uu: raise OSError("fixture write failure")
            return original(path,target)
        with mock.patch.object(desktop,"_apply_one",side_effect=fail_on_uu), self.assertRaises(desktop.DesktopError):
            self.restore()
        self.assertFalse(self.steam.exists())
        self.assertTrue(self.uu.exists())
        self.restore()
        self.install()
        self.steam.write_bytes(self.steam.read_bytes()+b"# user edit\n")
        uu_before=self.uu.read_bytes()
        with self.assertRaises(desktop.DesktopError):
            self.restore()
        self.assertIn(b"# user edit",self.steam.read_bytes())
        self.assertEqual(self.uu.read_bytes(),uu_before)

    def test_missing_native_steam_file_and_system_target_fail_before_changes(self):
        (self.system/"steam.desktop").unlink()
        with self.assertRaises(desktop.DesktopError):
            self.install()
        self.assertFalse(self.uu.exists())
        with self.assertRaises(desktop.DesktopError):
            desktop.install(self.helper,self.state,apps_dir=self.system,system_dirs=[self.system],home=self.home,config_home=self.config)


if __name__ == "__main__":
    unittest.main()
