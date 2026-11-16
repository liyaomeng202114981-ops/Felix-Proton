# SPDX-License-Identifier: BSD-3-Clause
"""Material and orchestration checks; no client, account or real network is used."""
import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("felix_first_setup", Path(__file__).with_name("setup.py"))
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def asset(name, data):
    return {"filename": name, "url": setup.DOWNLOAD_BASE + name,
            "sha256": hashlib.sha256(data).hexdigest(), "max_bytes": len(data) + 16}


class Response(io.BytesIO):
    def __init__(self, body, *, url="https://release-assets.githubusercontent.com/fixture", headers=None):
        super().__init__(body)
        self.url = url
        self.headers = {"Content-Length": str(len(body))} if headers is None else headers

    def geturl(self):
        return self.url


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="felix-setup-test-")))
        self.home = self.root / "home 中文"
        self.home.mkdir()
        self.enterContext(mock.patch.dict(os.environ, {
            "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "config"),
            "XDG_DATA_HOME": str(self.home / "data"), "XDG_CACHE_HOME": str(self.home / "cache"),
            "XDG_STATE_HOME": str(self.home / "state"), "DISPLAY": ":fixture"}))
        self.body = b"fixed dependency fixture\n"
        self.asset = asset("dependency", self.body)
        self.cache = self.home / "downloads"
        self.assets = {"runner": {"filename": setup.bootstrap.ARCHIVE,
                                 "url": setup.DOWNLOAD_BASE + setup.bootstrap.ARCHIVE,
                                 "sha256": setup.bootstrap.SHA256, "max_bytes": 1024**3},
                       "wrapper": asset("shorin-proton-wrapper", self.body),
                       "pasta": asset("pasta-fixture", self.body)}
        self.manifest = self.root / "downloads.json"
        self.write_manifest(self.assets)

    def write_manifest(self, assets):
        self.manifest.write_text(json.dumps({"schema": "felix-setup-downloads-v1", "assets": assets}))

    def obtain(self, opener, **kwargs):
        return setup.obtain(self.asset, cache=self.cache, local_dirs=[], opener=opener, **kwargs)

    def args(self, *extras):
        return setup.parser().parse_args(["install", "--uu-installer", str(self.home / "UU 官方.exe"), *extras])

    def report(self, **changes):
        return dict(ready=False, issues=[setup.MISSING_WRAPPER, setup.MISSING_PASTA], warnings=[],
                    wrapper=None, pasta_bin_dir=None, runner=None) | changes

    def install_mocks(self):
        self.enterContext(mock.patch.object(setup, "require_user_home"))
        self.enterContext(mock.patch.object(setup, "read_manifest", return_value=self.assets))
        self.enterContext(mock.patch.object(setup.bootstrap, "inspect_installer", return_value=("fixture", "sha")))
        self.enterContext(mock.patch.object(setup, "check", return_value=self.report()))
        return self.enterContext(mock.patch.object(setup.enable, "enable", return_value={"changed": False}))

    def owned_configuration(self):
        steam = self.home / "private Steam"
        runner = steam / "compatibilitytools.d" / setup.bootstrap.TOOL / "proton"
        runner.parent.mkdir(parents=True)
        runner.write_bytes(b"version-checked runner fixture")
        runner.chmod(0o755)
        self.enterContext(mock.patch.dict(setup.setup_config.IDENTITY,
            {"proton": hashlib.sha256(runner.read_bytes()).hexdigest()}, clear=True))
        prefix = self.home / "Games" / ("Felix-UU-" + setup.setup_config.VERSION)
        prefix.mkdir(mode=0o700, parents=True)
        for name, body in ((".felix-uu-test-owner", setup.setup_config.OWNER + "\n"),
                           (".shorin-proton-wrapper.conf", "netns=1\n")):
            file = prefix / name
            file.write_text(body)
            file.chmod(0o600)
        binaries = self.home / "private dependencies"
        binaries.mkdir()
        for name in ("wrapper", "native-steam", "pasta"):
            file = binaries / name
            file.write_text("#!/bin/sh\nexit 0\n")
            file.chmod(0o755)
        config = self.home / "config/felix-uu-test" / setup.setup_config.VERSION / "config.json"
        config.parent.mkdir(mode=0o700, parents=True)
        config.write_text(json.dumps({"prefix": str(prefix), "runner": str(runner),
            "wrapper": str(binaries / "wrapper"), "steam_real": str(binaries / "native-steam"),
            "pasta_bin_dir": str(binaries)}))
        config.chmod(0o600)
        return config, runner, binaries, steam

    def test_manifest_enforces_fixed_runner_and_only_own_release_urls(self):
        self.assertEqual(setup.read_manifest(self.manifest), self.assets)
        for key, value in (("sha256", "0" * 64), ("filename", "other.tar.zst"),
                           ("url", "https://example.invalid/runner")):
            altered = copy.deepcopy(self.assets)
            altered["runner"][key] = value
            self.write_manifest(altered)
            with self.assertRaises(setup.SetupError):
                setup.read_manifest(self.manifest)
        self.write_manifest(self.assets)
        self.manifest.unlink()
        self.manifest.symlink_to(self.root / "missing")
        with self.assertRaises(setup.SetupError):
            setup.read_manifest(self.manifest)

    def test_manifest_rejects_traversal_boolean_limits_and_extra_executables(self):
        for key, value in (("filename", "../pasta"), ("max_bytes", True), ("max_bytes", -1)):
            altered = copy.deepcopy(self.assets)
            altered["pasta"][key] = value
            self.write_manifest(altered)
            with self.assertRaises(setup.SetupError):
                setup.read_manifest(self.manifest)
        altered = copy.deepcopy(self.assets)
        altered["unknown"] = self.asset
        self.write_manifest(altered)
        with self.assertRaises(setup.SetupError):
            setup.read_manifest(self.manifest)

    def test_download_publishes_only_verified_complete_file_and_reuses_cache(self):
        opener = mock.Mock(side_effect=lambda *a, **kw: Response(self.body))
        downloaded = self.obtain(opener)
        self.assertEqual(downloaded.read_bytes(), self.body)
        self.assertEqual(downloaded.stat().st_mode & 0o777, 0o600)
        self.assertEqual({p.name for p in self.cache.iterdir()}, {"dependency"})
        self.assertEqual(self.obtain(opener), downloaded)
        opener.assert_called_once()

    def test_bad_hash_and_oversize_leave_no_partial_or_executable_file(self):
        for body, headers in ((b"corrupted", {}), (b"x" * 500, {}),
                              (self.body, {"Content-Length": "9999999"})):
            with self.assertRaises(setup.SetupError):
                self.obtain(lambda *a, **kw: Response(body, headers=headers))
            self.assertEqual(list(self.cache.iterdir()), [])

    def test_download_rejects_insecure_or_unrelated_redirects(self):
        for url in ("http://github.com/fixture", "https://example.invalid/fixture",
                    "https://github.com:8443/fixture", "https://user@github.com/fixture"):
            with self.assertRaises(setup.SetupError):
                self.obtain(lambda *a, **kw: Response(self.body, url=url))
            self.assertEqual(list(self.cache.iterdir()), [])

    def test_interrupted_download_removes_own_temporary_file(self):
        class Broken(Response):
            def read(self, count=-1):
                if self.tell():
                    raise OSError("connection interrupted")
                return super().read(3)
        with self.assertRaises(OSError):
            self.obtain(lambda *a, **kw: Broken(self.body))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_offline_missing_material_does_not_create_cache(self):
        with self.assertRaisesRegex(setup.SetupError, "离线材料缺失"):
            self.obtain(mock.Mock(side_effect=AssertionError("no HTTP")), offline=True)
        self.assertFalse(self.cache.exists())

    def test_cache_or_dependency_conflict_is_preserved(self):
        self.cache.mkdir(mode=0o700)
        target = self.cache / "dependency"
        target.write_bytes(b"unrecognized")
        with self.assertRaises(setup.SetupError):
            self.obtain(mock.Mock(side_effect=AssertionError("no HTTP")))
        self.assertEqual(target.read_bytes(), b"unrecognized")
        source = self.root / "pasta"
        source.write_bytes(self.body)
        installed = setup.install_dependency("pasta", source, self.asset)
        self.assertEqual(installed.name, "pasta")
        self.assertTrue(os.access(installed, os.X_OK))
        before = installed.stat().st_mtime_ns
        self.assertEqual(setup.install_dependency("pasta", source, self.asset), installed)
        self.assertEqual(installed.stat().st_mtime_ns, before)
        installed.write_bytes(b"user change")
        with self.assertRaises(setup.SetupError):
            setup.install_dependency("pasta", source, self.asset)
        self.assertEqual(installed.read_bytes(), b"user change")

    def test_dependency_parent_symlink_is_refused(self):
        data = self.home / "data"
        data.mkdir()
        other = self.root / "other"
        other.mkdir()
        (data / "felix-proton-setup").symlink_to(other, target_is_directory=True)
        source = self.root / "source"
        source.write_bytes(self.body)
        with self.assertRaises(setup.SetupError):
            setup.install_dependency("pasta", source, self.asset)
        self.assertFalse(list(other.iterdir()))

    def test_fresh_install_requires_valid_official_installer_before_download(self):
        self.install_mocks()
        args = setup.parser().parse_args(["install"])
        with mock.patch.object(setup, "obtain", side_effect=AssertionError("no download")):
            with self.assertRaisesRegex(setup.SetupError, "--uu-installer"):
                setup.install(args)
            with mock.patch.object(setup.bootstrap, "inspect_installer", side_effect=setup.SetupError("bad PE")):
                with self.assertRaisesRegex(setup.SetupError, "bad PE"):
                    setup.install(self.args())

    def test_system_issue_stops_before_download_or_native_install(self):
        native = self.install_mocks()
        report = self.report()
        report["issues"].append("missing native Steam")
        with mock.patch.object(setup, "check", return_value=report), mock.patch.object(
                setup, "obtain", side_effect=AssertionError("no download")):
            with self.assertRaisesRegex(setup.SetupError, "missing native Steam"):
                setup.install(self.args())
        native.assert_not_called()

    def test_explicit_offline_materials_are_forwarded_and_no_materials_download(self):
        native = self.install_mocks()
        args = self.args("--offline", "--wrapper", "/fixture/wrapper", "--pasta", "/fixture/pasta",
                         "--steam-root", "/fixture/Steam", "--steam", "/fixture/native-steam",
                         "--runner-archive", str(self.root / "runner.tar.zst"))
        with mock.patch.object(setup, "check", return_value=self.report(ready=True, issues=[],
                    wrapper="/fixture/wrapper", pasta_bin_dir="/fixture")), mock.patch.object(
                setup, "verify_file") as verify, mock.patch.object(
                setup, "obtain", side_effect=AssertionError("no download")), mock.patch.object(
                setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            result = setup.install(args)
        forwarded = native.call_args.args[0]
        self.assertEqual(forwarded.wrapper, args.wrapper)
        self.assertEqual(forwarded.pasta, args.pasta)
        self.assertEqual(forwarded.steam_root, args.steam_root)
        self.assertEqual(forwarded.steam, args.steam)
        self.assertEqual(forwarded.archive, args.runner_archive)
        verify.assert_called_once_with(args.runner_archive, self.assets["runner"])
        self.assertTrue(result["pairing_tool_installed"])

    def test_resume_uses_owned_config_without_replacing_existing_dependencies(self):
        native = self.install_mocks()
        existing = self.home / "config/felix-uu-test" / setup.setup_config.VERSION / "config.json"
        existing.parent.mkdir(parents=True)
        existing.write_text("identity validated by the real native installer")
        with mock.patch.object(setup, "obtain", side_effect=AssertionError("no download")), mock.patch.object(
                setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            setup.install(setup.parser().parse_args(["install"]))
        forwarded = native.call_args.args[0]
        self.assertIsNone(forwarded.archive)
        self.assertIsNone(forwarded.wrapper)
        self.assertIsNone(forwarded.pasta)

    def test_pairing_failure_retains_successful_native_install_and_reports_partial_result(self):
        native = self.install_mocks()
        existing = self.home / "config/felix-uu-test" / setup.setup_config.VERSION / "config.json"
        existing.parent.mkdir(parents=True)
        existing.touch()
        with mock.patch.object(setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)):
            with self.assertRaisesRegex(setup.SetupError, "底层集成已安装"):
                setup.install(setup.parser().parse_args(["install"]))
        native.assert_called_once()

    def test_check_and_root_refusal_do_not_create_user_state(self):
        with mock.patch.object(setup.bootstrap, "discover", return_value=self.report()), mock.patch.object(
                setup.os.path, "isfile", return_value=True), mock.patch.object(setup.os, "access", return_value=True), mock.patch.object(
                setup, "frontend_issues", return_value=[]), mock.patch.object(setup.os, "geteuid", return_value=1000):
            report = setup.check(self.args())
        self.assertEqual(report["automatic_materials"], ["wrapper", "pasta"])
        self.assertTrue(report["host_ready"])
        self.assertTrue(report["ready"])
        with mock.patch.object(setup.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(setup.SetupError, "sudo/root"):
                setup.require_user_home()
        self.assertEqual(list(self.home.iterdir()), [])

    def test_missing_gui_or_locale_is_reported_before_any_install(self):
        with mock.patch.object(setup.subprocess, "run", side_effect=[subprocess.CompletedProcess([], 1),
                                                                  subprocess.CompletedProcess([], 1)]) as run:
            issues = setup.frontend_issues()
        self.assertEqual(len(issues), 2)
        self.assertIn("GTK 4.10+", issues[0])
        self.assertIn("zh_CN.UTF-8", issues[1])
        self.assertTrue(all(call.args[0][:3] == ["/usr/bin/python3", "-B", "-c"] for call in run.call_args_list))

    def test_runtime_download_tools_are_host_requirements(self):
        with mock.patch.object(setup.bootstrap, "discover", return_value=self.report()), mock.patch.object(
                setup, "frontend_issues", return_value=[]), mock.patch.object(setup, "require_user_home"), mock.patch.object(
                setup.shutil, "which", return_value=None), mock.patch.object(setup.os.path, "isfile", return_value=True), mock.patch.object(
                setup.os, "access", return_value=True):
            report = setup.check(self.args())
        self.assertFalse(report["host_ready"])
        self.assertTrue(any("curl 或 wget" in issue for issue in report["issues"]))
        self.assertTrue(any(" tar" in issue for issue in report["issues"]))
        self.assertTrue(any(" xz" in issue for issue in report["issues"]))

    def test_bundled_pasta_libc_requirement_does_not_reject_valid_custom_pasta(self):
        with mock.patch.object(setup, "frontend_issues", return_value=[]), mock.patch.object(
                setup, "require_user_home"), mock.patch.object(setup.os, "confstr", return_value="glibc 2.37"), mock.patch.object(
                setup.os.path, "isfile", return_value=True), mock.patch.object(setup.os, "access", return_value=True):
            with mock.patch.object(setup.bootstrap, "discover", return_value=self.report()):
                automatic = setup.check(self.args())
            self.assertTrue(any("glibc 2.38+" in issue for issue in automatic["issues"]))
            args = self.args("--pasta", "/fixture/pasta")
            with mock.patch.object(setup.bootstrap, "discover", return_value=self.report(
                    issues=[setup.MISSING_WRAPPER], pasta_bin_dir="/fixture")):
                custom = setup.check(args)
            self.assertFalse(any("glibc" in issue for issue in custom["issues"]))

    def test_readonly_check_reuses_private_owned_dependencies_without_path_changes(self):
        config, runner, binaries, steam = self.owned_configuration()
        before = {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        found = setup.discover_options(setup.parser().parse_args(["check"]))
        self.assertEqual(found["pasta"], binaries / "pasta")
        self.assertEqual(found["wrapper"], binaries / "wrapper")
        self.assertEqual(found["steam_root"], steam)
        self.assertEqual(before, {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()})
        with self.assertRaisesRegex(setup.SetupError, "与已有配置不同"):
            setup.discover_options(setup.parser().parse_args(["check", "--wrapper", "/unrelated/wrapper"]))

    def test_existing_configuration_with_changed_runner_is_not_used_for_check(self):
        config, runner, binaries, steam = self.owned_configuration()
        runner.write_bytes(b"foreign runtime")
        before = config.read_bytes()
        with self.assertRaises(setup.SetupError):
            setup.discover_options(setup.parser().parse_args(["check"]))
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(runner.read_bytes(), b"foreign runtime")


if __name__ == "__main__":
    unittest.main()
