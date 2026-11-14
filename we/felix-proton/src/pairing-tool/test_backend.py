# SPDX-License-Identifier: BSD-3-Clause
"""Fixture-only pairing transactions. No client, wrapper or network is started."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import ACCELERATOR_ID, IDS, PLATFORM_ID, PairingError, PairingService


STEAM = ("# personal note\n[Desktop Entry]\nType=Application\nName=Steam\n"
         "Name[zh_CN]=我的 Steam\nIcon=steam-original\nExec=/usr/bin/steam %U\n"
         "MimeType=x-scheme-handler/steam;\nActions=Library;Friends;\nStartupWMClass=Steam\n\n"
         "[Desktop Action Library]\nName=Library\nExec=/usr/bin/steam steam://open/games\n\n"
         "[Desktop Action Friends]\nName=Friends\nExec=/usr/bin/steam -silent steam://open/friends\n").encode()
UU = ("[Desktop Entry]\nType=Application\nName=网易 UU 加速器\n"
      "Icon=/fixture/original-uu.png\nExec=/fixture/old-uu\nStartupWMClass=uu.exe\n").encode()


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.root / "fixture-home"
        self.apps = self.home / ".local/share/applications"
        self.apps.mkdir(parents=True)
        self.system = self.root / "system-apps"
        self.system.mkdir()
        self.helper = self.home / ".local/share/felix-native-ux/v1/routes.py"
        self.helper.parent.mkdir(parents=True)
        for name in ("routes.py", "cm_guard.py", "policy.py", "endpoints.py", "steam_window.py"):
            (self.helper.parent / name).write_text("# fixture; never executed\n")
        prefix = self.home / "prefix"
        (prefix / "pfx").mkdir(parents=True)
        (prefix / "pfx/system.reg").write_text("fixture")
        client = prefix / "pfx/uu.exe"
        client.write_bytes(b"fixture")
        (prefix / ".shorin-proton-wrapper.conf").write_text("netns=1\n")
        executable = self.root / "fixture-executable"
        executable.write_text("#!/bin/sh\nexit 99\n")
        executable.chmod(0o700)
        self.runtime = executable.parent / "felix"
        for relative in ("local-beta.py", "observe.py", "net_beta.py",
                         "launchers/uu-network-launch", "launchers/uu-network-steam", "launchers/uu-network-run"):
            dependency = self.runtime / relative
            dependency.parent.mkdir(parents=True, exist_ok=True)
            dependency.write_text("# fixture; never executed\n")
            dependency.chmod(0o700)
        self.config = self.home / ".config/fixture-network/config.json"
        self.write_json(self.config, {"prefix": str(prefix), "runner": str(executable),
                                     "wrapper": str(executable), "steam_real": str(executable),
                                     "uu_executable": str(client)})
        self.write_json(self.home / ".config/felix-native-ux/active.json", {"config": str(self.config)})
        self.service = PairingService(home=self.home, system_dirs=[self.system])
        self.steam = self.apps / PLATFORM_ID
        self.uu = self.apps / ACCELERATOR_ID
        self.uu_data = UU.replace(b"/fixture/old-uu", os.fsencode(self.home / ".local/lib/uu-accelerator/launch"))
        self.steam.write_bytes(STEAM)
        self.uu.write_bytes(self.uu_data)

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def pair(self):
        return self.service.pair(*IDS)

    def wire_existing(self):
        desktop = self.service.desktop
        for name, data in ((PLATFORM_ID, STEAM), (ACCELERATOR_ID, self.uu_data)):
            role = "steam" if name == PLATFORM_ID else "uu"
            command = "/usr/bin/python3 " + desktop._quote(self.helper) + " " + role
            (self.apps / name).write_bytes(desktop._rewrite(data, name, command, self.home, role == "steam"))

    def test_inspection_is_read_only_and_unknown_ids_do_not_write(self):
        result = self.service.inspect()
        self.assertTrue(result["ready"])
        self.assertFalse(result["connected"])
        self.assertFalse(self.service.private.exists())
        for ids in (("renamed-steam.desktop", ACCELERATOR_ID), (PLATFORM_ID, "other.desktop")):
            with self.subTest(ids=ids), self.assertRaises(PairingError):
                self.service.pair(*ids)
        self.assertFalse(self.service.private.exists())
        self.assertEqual(self.steam.read_bytes(), STEAM)
        self.assertEqual(self.uu.read_bytes(), self.uu_data)

    def test_pair_keeps_icons_names_actions_uris_and_only_changes_two_execs(self):
        untouched = self.apps / "steam-uu.desktop"
        untouched.write_bytes(b"legacy remains hidden or unchanged")
        result = self.pair()
        self.assertTrue(result["connected"])
        self.assertTrue(result["managed"])
        self.assertFalse(result["adopted"])
        steam_command = ("/usr/bin/python3 " + self.service.desktop._quote(self.helper) + " steam").encode()
        self.assertEqual(self.steam.read_bytes(), STEAM.replace(b"/usr/bin/steam", steam_command))
        self.assertEqual(self.uu.read_bytes(), self.uu_data.replace(os.fsencode(self.home / ".local/lib/uu-accelerator/launch"),
            ("/usr/bin/python3 " + self.service.desktop._quote(self.helper) + " uu").encode()))
        self.assertEqual(untouched.read_bytes(), b"legacy remains hidden or unchanged")
        self.assertEqual(self.service.private.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.service.ledger.stat().st_mode & 0o777, 0o600)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.steam, self.uu)}
        self.pair()
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}, before)

    def test_custom_uu_command_or_extra_arguments_are_preserved_and_pairing_refused(self):
        legacy = os.fsencode(self.home / ".local/lib/uu-accelerator/launch")
        for command in (b"/custom/uu-wrapper --personal-option", legacy + b" --personal-option"):
            with self.subTest(command=command):
                custom = self.uu_data.replace(legacy, command)
                self.uu.write_bytes(custom)
                with self.assertRaisesRegex(PairingError, "自定义命令或参数"):
                    self.pair()
                self.assertEqual(self.uu.read_bytes(), custom)
                self.assertEqual(self.steam.read_bytes(), STEAM)
                self.assertFalse(self.service.ledger.exists())

    def test_remove_restores_exact_files_metadata_and_keeps_other_entries(self):
        self.steam.chmod(0o640)
        os.utime(self.steam, ns=(1700000000000000000, 1700000001000000000))
        self.pair()
        result = self.service.remove()
        self.assertFalse(result["managed"])
        self.assertFalse(result["connected"])
        self.assertEqual(self.steam.read_bytes(), STEAM)
        self.assertEqual(self.uu.read_bytes(), self.uu_data)
        self.assertEqual(self.steam.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.steam.stat().st_mtime_ns, 1700000001000000000)
        self.assertFalse(self.service.ledger.exists())

    def test_existing_connection_is_adopted_without_desktop_writes_or_legacy_restore(self):
        self.wire_existing()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.steam, self.uu)}
        real = self.service.desktop._atomic
        written = []
        def track(path, *args, **kwargs):
            written.append(Path(path))
            return real(path, *args, **kwargs)
        with patch.object(self.service.desktop, "_atomic", side_effect=track), \
             patch.object(self.service.desktop, "restore", side_effect=AssertionError("must not use legacy restore")):
            result = self.pair()
            self.assertTrue(result["adopted"])
            result = self.service.remove()
        self.assertTrue(result["connected"])
        self.assertFalse(result["managed"])
        self.assertIn("保留", result["message"])
        self.assertFalse(any(path in before for path in written))
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}, before)

    def test_external_desktop_edit_refuses_pair_and_remove_and_preserves_journal(self):
        self.pair()
        changed = self.steam.read_bytes() + b"# another editor\n"
        self.steam.write_bytes(changed)
        uu = self.uu.read_bytes()
        for action in (self.pair, self.service.remove):
            with self.assertRaises(PairingError):
                action()
            self.assertEqual(self.steam.read_bytes(), changed)
            self.assertEqual(self.uu.read_bytes(), uu)
            self.assertTrue(self.service.ledger.exists())
        self.assertFalse(self.service.inspect()["ready"])
        self.assertTrue(self.service.inspect()["managed"])

    def test_second_write_failure_compensates_first_and_removes_clean_journal(self):
        apply = self.service._apply_snapshot
        count = [0]
        def fail_second(*args):
            count[0] += 1
            if count[0] == 2:
                raise OSError("fixture second write failure")
            return apply(*args)
        with patch.object(self.service, "_apply_snapshot", side_effect=fail_second), self.assertRaises(PairingError):
            self.pair()
        self.assertEqual(self.steam.read_bytes(), STEAM)
        self.assertEqual(self.uu.read_bytes(), self.uu_data)
        self.assertFalse(self.service.ledger.exists())

    def test_failed_compensation_retains_recoverable_journal_and_remove_can_finish(self):
        apply = self.service._apply_snapshot
        count = [0]
        def fail_second_and_rollback(*args):
            count[0] += 1
            if count[0] in (2, 4):
                raise OSError("fixture write unavailable")
            return apply(*args)
        with patch.object(self.service, "_apply_snapshot", side_effect=fail_second_and_rollback), self.assertRaises(PairingError):
            self.pair()
        self.assertEqual(json.loads(self.service.ledger.read_text())["phase"], "recovery")
        self.service.remove()
        self.assertEqual(self.steam.read_bytes(), STEAM)
        self.assertEqual(self.uu.read_bytes(), self.uu_data)
        self.assertFalse(self.service.ledger.exists())

    def test_system_entry_is_overridden_not_modified_and_override_removed_on_unpair(self):
        self.steam.unlink()
        source = self.system / PLATFORM_ID
        source.write_bytes(STEAM)
        self.pair()
        self.assertEqual(source.read_bytes(), STEAM)
        self.assertTrue(self.steam.exists())
        self.service.remove()
        self.assertFalse(self.steam.exists())
        self.assertEqual(source.read_bytes(), STEAM)
        self.assertEqual(self.uu.read_bytes(), self.uu_data)

    def test_interrupted_preparing_journal_can_resume_or_restore_before_state(self):
        self.pair()
        record = json.loads(self.service.ledger.read_text())
        record["phase"] = "preparing"
        self.service._apply_snapshot(ACCELERATOR_ID, record["files"][ACCELERATOR_ID]["before"],
                                     record["files"][ACCELERATOR_ID]["after"])
        self.service._save(record)
        self.assertFalse(self.service.inspect()["connected"])
        self.assertFalse(self.service.inspect()["ready"])
        self.assertEqual(self.service.inspect()["phase"], "preparing")
        self.assertTrue(self.pair()["connected"])
        self.service.remove()
        self.assertEqual(self.steam.read_bytes(), STEAM)
        self.assertEqual(self.uu.read_bytes(), self.uu_data)

    def test_missing_or_public_config_refuses_without_touching_desktops(self):
        for mode in (0o644, None):
            with self.subTest(mode=mode):
                if mode is None:
                    self.config.unlink()
                else:
                    self.config.chmod(mode)
                self.assertFalse(self.service.inspect()["ready"])
                with self.assertRaises(PairingError):
                    self.pair()
                self.assertEqual(self.steam.read_bytes(), STEAM)
                self.assertEqual(self.uu.read_bytes(), self.uu_data)
        self.assertFalse(self.service.ledger.exists())

    def test_missing_runtime_components_refuse_ready_and_do_not_write_desktops(self):
        for relative in ("local-beta.py", "observe.py", "net_beta.py",
                         "launchers/uu-network-launch", "launchers/uu-network-steam", "launchers/uu-network-run"):
            with self.subTest(relative=relative):
                dependency = self.runtime / relative
                dependency.unlink()
                self.assertFalse(self.service.inspect()["ready"])
                with self.assertRaises(PairingError):
                    self.pair()
                self.assertEqual(self.steam.read_bytes(), STEAM)
                self.assertEqual(self.uu.read_bytes(), self.uu_data)
                self.assertFalse(self.service.ledger.exists())
                dependency.write_text("# fixture; never executed\n")
                dependency.chmod(0o700)

    def test_remove_does_not_need_deleted_runtime_config(self):
        self.pair()
        self.config.unlink()
        result = self.service.remove()
        self.assertFalse(result["managed"])
        self.assertEqual(self.steam.read_bytes(), STEAM)
        self.assertEqual(self.uu.read_bytes(), self.uu_data)

    def test_adopted_connection_changed_externally_is_not_reported_ready(self):
        self.wire_existing()
        self.pair()
        self.steam.write_bytes(STEAM)
        result = self.service.inspect()
        self.assertFalse(result["ready"])
        self.assertFalse(result["connected"])
        self.assertTrue(result["managed"])
        self.assertTrue(result["adopted"])
        with self.assertRaises(PairingError):
            self.pair()
        self.service.remove()
        self.assertEqual(self.steam.read_bytes(), STEAM)

    def test_reopened_service_and_repeat_pair_are_persistent_without_rewriting(self):
        self.pair()
        paths = (self.steam, self.uu, self.service.ledger)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) for path in paths}
        reopened = PairingService(home=self.home, system_dirs=[self.system])
        with patch.object(reopened, "_save", side_effect=AssertionError("unexpected ledger write")), \
             patch.object(reopened, "_apply_snapshot", side_effect=AssertionError("unexpected desktop write")):
            for result in (reopened.inspect(), reopened.pair(*IDS), reopened.inspect()):
                self.assertTrue(result["ready"] and result["connected"] and result["managed"])
        self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
                                  for path in paths})

    def test_locale_and_json_format_changes_do_not_invalidate_saved_pair(self):
        self.pair()
        ledger = self.service.ledger.read_bytes()
        config = json.loads(self.config.read_text())
        config["uu_locale"] = "en_US.UTF-8"
        self.config.write_text(json.dumps(config, indent=4, sort_keys=True) + "\n")
        reopened = PairingService(home=self.home, system_dirs=[self.system])
        self.assertTrue(reopened.inspect()["ready"])
        self.assertTrue(reopened.pair(*IDS)["ready"])
        self.assertEqual(reopened.ledger.read_bytes(), ledger)

    def test_unchanged_legacy_record_upgrades_without_touching_desktops_or_backups(self):
        self.pair()
        record = json.loads(self.service.ledger.read_text())
        record.pop("connection_identity")
        self.write_json(self.service.ledger, record)
        before = {path: path.read_bytes() for path in (self.steam, self.uu)}
        with patch.object(self.service, "_apply_snapshot", side_effect=AssertionError("desktop write")):
            self.assertTrue(self.service.upgrade_record())
            self.assertFalse(self.service.upgrade_record())
        upgraded = json.loads(self.service.ledger.read_text())
        self.assertEqual({key: value for key, value in upgraded.items() if key != "connection_identity"}, record)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        config = json.loads(self.config.read_text())
        config["uu_locale"] = "zh_CN.UTF-8"
        self.write_json(self.config, config)
        self.assertTrue(self.service.inspect()["ready"])

    def test_changed_legacy_record_cannot_be_silently_rebased(self):
        self.pair()
        record = json.loads(self.service.ledger.read_text())
        record.pop("connection_identity")
        self.write_json(self.service.ledger, record)
        original = self.service.ledger.read_bytes()
        config = json.loads(self.config.read_text())
        config["uu_locale"] = "en_US.UTF-8"
        self.write_json(self.config, config)
        with self.assertRaises(PairingError):
            self.service.upgrade_record()
        self.assertEqual(self.service.ledger.read_bytes(), original)

    def test_config_path_and_values_change_refuse_stale_pair_but_remove_still_restores(self):
        for change in ("path", "prefix", "runner", "uu_executable"):
            with self.subTest(change=change):
                self.pair()
                config = json.loads(self.config.read_text())
                original = dict(config)
                active = self.home / ".config/felix-native-ux/active.json"
                if change == "path":
                    new = self.config.with_name("replacement.json")
                    self.write_json(new, config)
                    self.write_json(active, {"config": str(new)})
                elif change == "prefix":
                    # An equivalent on-disk fixture under another configured path
                    # still changes which prefix the future wrapper will use.
                    alias = Path(config["prefix"]).with_name("alias-prefix")
                    alias.symlink_to(config["prefix"], target_is_directory=True)
                    config["prefix"] = str(alias)
                    self.write_json(self.config, config)
                else:
                    replacement = Path(config[change]).with_name("replacement-" + change)
                    replacement.write_bytes(Path(config[change]).read_bytes())
                    replacement.chmod(0o700)
                    config[change] = str(replacement)
                    self.write_json(self.config, config)
                result = self.service.inspect()
                self.assertFalse(result["ready"])
                self.assertTrue(result["managed"])
                self.assertIn("配置已变化", result["message"])
                with self.assertRaises(PairingError):
                    self.pair()
                self.service.remove()
                self.assertEqual(self.steam.read_bytes(), STEAM)
                self.assertEqual(self.uu.read_bytes(), self.uu_data)
                self.write_json(active, {"config": str(self.config)})
                self.write_json(self.config, original)


if __name__ == "__main__":
    unittest.main()
