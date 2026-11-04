# SPDX-License-Identifier: BSD-3-Clause
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

source = Path(__file__).resolve().parents[1] / "local-beta.py"
spec = importlib.util.spec_from_file_location("felix_beta_test_target", source)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class LocalBetaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="felix 中文 ")))
        self.personal = self.tmp / "fixture-user"
        self.enterContext(mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.tmp / "config"),
                                                      "XDG_DATA_HOME": str(self.tmp / "data")}))
        root = self.personal / ".local/share/Steam/compatibilitytools.d" / mod.PACKAGE
        self.b = mod.Beta(root, self.personal)
        self.proc = self.tmp / "proc"
        self.runtime = self.tmp / "runtime"
        self.proc.mkdir()
        self.runtime.mkdir()
        for path in (self.b.runner, self.b.portable / "uu-network-launch", self.b.portable / "uu-network-steam",
                     self.b.portable / "uu_network.py", self.b.observer, self.personal / ".local/bin/shorin-proton-wrapper",
                     self.personal / ".local/lib/steam-updater-font/launch", self.personal / ".local/lib/uu-accelerator/bin/pasta"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            path.chmod(0o755)

    def state(self):
        return mod.session_state(self.b, self.proc, self.runtime)

    def fake_process(self, pid, comm, image, prefix=None, ns="net:[200]"):
        p = self.proc / str(pid)
        (p / "ns").mkdir(parents=True)
        (p / "comm").write_bytes(comm + b"\n")
        (p / "exe").symlink_to(image)
        (p / "ns/net").symlink_to(ns)
        (p / "ns/user").symlink_to("user:[100]")
        (p / "environ").write_bytes(b"" if prefix is None else b"WINEPREFIX=" + os.fsencode(prefix) + b"/\0")
        return p

    def fake_keeper(self, prefix, pid=10):
        session = self.runtime / "shorin-proton-wrapper/sessions" / mod.digest(str(prefix.resolve()).encode())[:16]
        session.mkdir(parents=True)
        (session / "keeper.pid").write_text(str(pid))
        (session / "netns").write_text("net:[200]")
        (session / "userns").write_text("user:[100]")
        p = self.fake_process(pid, b"python3", "/usr/bin/python3")
        (p / "cmdline").write_bytes(b"python3\0-\0" + os.fsencode(session) + b"\0")
        return p

    def test_install_rerun_remove_preserves_prefix_and_private_config(self):
        self.b.install()
        cfg = json.loads(self.b.config.read_text())
        cfg["uu_locale"] = "C.UTF-8"
        self.b.config.write_text(json.dumps(cfg))
        self.b.install()
        self.assertEqual(self.b.read_config()["uu_locale"], "C.UTF-8")
        self.assertEqual(self.b.prefix.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.b.network_config.read_bytes(), b"netns=1\n")
        for path in self.b.desktop_files():
            self.assertIn("标记刚才异常", path.read_text())
            if shutil.which("desktop-file-validate"):
                subprocess.run(["desktop-file-validate", str(path)], check=True, capture_output=True)
        self.b.uninstall()
        self.assertFalse(any(p.exists() for p in self.b.desktop_files()))
        self.assertTrue(self.b.config.is_file())
        self.assertTrue(self.b.marker.is_file())
        self.assertFalse(self.b.stable.exists())

    def test_install_refuses_alien_prefix_and_desktop(self):
        self.b.prefix.mkdir(parents=True)
        (self.b.prefix / "existing").touch()
        with self.assertRaises(mod.Refused):
            self.b.install()
        self.assertFalse(self.b.manifest.exists())
        (self.b.prefix / "existing").unlink()
        self.b.apps.mkdir(parents=True)
        next(iter(self.b.desktop_files())).write_text("other owner")
        with self.assertRaises(mod.Refused):
            self.b.install()
        self.assertFalse(self.b.manifest.exists())

    def test_stable_symlink_refused_before_write(self):
        self.b.stable.mkdir(parents=True)
        self.b.prefix.symlink_to(self.b.stable, target_is_directory=True)
        with self.assertRaises(mod.Refused):
            self.b.install()
        self.assertFalse(any(self.b.stable.iterdir()))

    def test_interrupted_install_can_resume(self):
        original = mod.create_only
        def failing(path, data, mode=0o600):
            if path == self.b.marker:
                raise OSError("fixture interruption")
            return original(path, data, mode)
        with mock.patch.object(mod, "create_only", side_effect=failing), self.assertRaises(OSError):
            self.b.install()
        self.assertTrue(self.b.manifest.exists())
        self.b.install()
        self.assertTrue(all(p.exists() for p in self.b.desktop_files()))

    def test_uninstall_keeps_modified_desktop_and_its_sibling(self):
        self.b.install()
        paths = list(self.b.desktop_files())
        paths[0].write_text("user edit")
        with self.assertRaises(mod.Refused):
            self.b.uninstall()
        self.assertEqual(paths[0].read_text(), "user edit")
        self.assertTrue(paths[1].exists())

    def test_config_cannot_redirect_to_stable_prefix_or_runner(self):
        self.b.install()
        cfg = self.b.read_config()
        for field, bad_value in (("prefix", str(self.b.stable)), ("runner", "/old/proton"),
                                 ("uu_executable", str(self.b.stable / "pfx/UU.exe")),
                                 ("steam_real", str(self.personal / ".local/lib/uu-accelerator/steam"))):
            self.b.config.write_text(json.dumps(cfg | {field: bad_value}))
            with self.assertRaises(mod.Refused):
                self.b.read_config()

    def test_non_utf8_comm_cannot_block_start(self):
        self.fake_process(20, b"bad-\xff-name", "/unused")
        self.assertIsNone(self.state()["conflict"])

    def test_namespace_and_runner_conflicts(self):
        self.fake_keeper(self.b.prefix)
        self.fake_process(20, b"uu.exe", self.b.root / "files/bin/wine", self.b.prefix / "pfx")
        self.fake_process(30, b"steam", "/client/steam")
        self.assertTrue(self.state()["beta_uu"])
        self.assertIsNone(self.state()["conflict"])
        self.fake_process(40, b"steam", "/client/steam", ns="net:[300]")
        self.assertEqual(self.state()["reason"], "wrong-network")
        shutil.rmtree(self.proc / "40")
        self.fake_process(50, b"uu.exe", "/stable/files/bin/wine", self.b.stable / "pfx")
        self.assertEqual(self.state()["reason"], "mixed-runner")

    def test_stale_keeper_pid_does_not_admit_foreign_client(self):
        p = self.fake_keeper(self.b.prefix)
        (p / "cmdline").write_bytes(b"python3\0different\0")
        self.fake_process(30, b"steam", "/client/steam")
        self.assertEqual(self.state()["reason"], "wrong-network")

    def test_known_loader_aliases_and_pe_mapping(self):
        expected = self.b.root / "files/lib/wine/x86_64-unix/wine-preloader"
        expected.parent.mkdir(parents=True)
        expected.touch()
        p = self.fake_process(23, b"uu.exe", expected)
        self.assertTrue(mod.has_beta_image(p, Path("/run/host") / str(expected).lstrip("/"), self.b))
        self.assertTrue(mod.has_beta_image(p, Path("/container/alias/wine-preloader"), self.b))
        self.assertFalse(mod.has_beta_image(p, self.b.root.parent / "another/files/bin/wine", self.b))
        pe = self.b.prefix / "pfx/drive_c/UU/uu.exe"
        record = b"1000-2000 r-xp 00000000 00:01 1 "
        (p / "maps").write_bytes(record + os.fsencode(self.b.root / "files/lib/wine/x86_64-unix/ntdll.so") + b"\n")
        self.assertTrue(mod.has_beta_image(p, pe, self.b))
        (p / "maps").write_bytes(record + b"/unrelated/ntdll.so\n")
        self.assertFalse(mod.has_beta_image(p, pe, self.b))

    def test_start_uses_observer_and_beta_only_configuration(self):
        self.b.install()
        state = {"conflict": None, "reason": None, "beta_uu": True, "beta_network": "net:[200]", "client_installed": True}
        with mock.patch.object(self.b, "check", return_value=state), mock.patch.object(os, "execve") as execute, \
             mock.patch.dict(os.environ, {"UU_PREFIX": str(self.b.stable), "UU_RUNNER": "/bad/proton"}):
            self.b.launch("uu", SimpleNamespace())
            _, argv, env = execute.call_args.args
            self.assertEqual(argv[1:], [str(self.b.observer), "exec", "--prefix", str(self.b.prefix),
                                       "--action", "uu", "--", str(self.b.portable / "uu-network-launch")])
            self.assertEqual(env["UU_NETWORK_CONFIG"], str(self.b.config))
            self.assertNotIn("UU_PREFIX", env)
            self.assertNotIn("UU_RUNNER", env)
            self.assertEqual(env["PROTON_DESKTOP_IMPORT"], "0")
            self.assertEqual(env["PROTON_NO_FSYNC"], "1")
            self.b.launch("steam", SimpleNamespace(arguments=["steam://open/library"]))
            self.assertEqual(execute.call_args.args[1][-1], "steam://open/library")

    def test_steam_needs_test_client_and_implicit_setup_rejects_changed_file(self):
        self.b.install()
        state = {"conflict": None, "reason": None, "beta_uu": False, "beta_network": None, "client_installed": False}
        self.b.installer.parent.mkdir(parents=True, exist_ok=True)
        self.b.installer.write_bytes(b"MZdummy")
        with mock.patch.object(self.b, "check", return_value=state), mock.patch.object(os, "execve") as execute:
            with self.assertRaises(mod.Refused):
                self.b.launch("steam", SimpleNamespace(arguments=[]))
            with self.assertRaises(mod.Refused):
                self.b.launch("uu", SimpleNamespace())
            execute.assert_not_called()

    def test_unattended_requires_known_digest_and_uses_separate_arguments(self):
        self.b.install()
        state = {"conflict": None, "reason": None, "beta_uu": False, "beta_network": None, "client_installed": False}
        selected = self.tmp / "explicit installer.exe"
        selected.write_bytes(b"MZfixture")
        args = SimpleNamespace(installer=str(selected), unattended=True)
        with mock.patch.object(self.b, "check", return_value=state), mock.patch.object(os, "execve") as execute:
            with self.assertRaisesRegex(mod.Refused, "无人值守"):
                self.b.launch("setup", args)
            execute.assert_not_called()
            with mock.patch.object(mod, "SETUP_SHA256", mod.digest(selected.read_bytes())):
                self.b.launch("setup", args)
            argv = execute.call_args.args[1]
            self.assertEqual(argv[-5:], [str(selected), "/silent", "/install_path",
                                         r"C:\Program Files (x86)\Netease\UU", "/no_launch_uu"])
            args.unattended = False
            self.b.launch("setup", args)
            self.assertEqual(execute.call_args.args[1][-1], str(selected))
            self.assertNotIn("/silent", execute.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
