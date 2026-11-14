# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Felix Li, with OpenAI Codex assistance.
"""Build/extract disposable packages; never install them or start a client."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

import build_release


class ReleasePackageTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="pairing-release-test-")))
        self.source = self.root / "source"
        self.source.mkdir()
        original = Path(__file__).resolve().parent
        for name in build_release.SOURCE_FILES:
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            path = original / name
            if path.is_file():
                target.write_bytes(path.read_bytes())
            elif name == "lib/desktop.py":
                target.write_bytes((original.parent / "native-ux/desktop.py").read_bytes())
            elif name in ("LICENSE", "COPYRIGHT", "TEST_RESULTS.md", "RELEASE_NOTES.md"):
                # A self-contained test fixture may precede documentation edits;
                # the actual builder still strictly requires every real file.
                target.write_text("Fixture-only " + name + "\n")
            else:
                self.fail("Missing test fixture source: " + name)
        # Package tests use a fixed fixture version, independent of a future
        # production VERSION bump that triggers the release workflow.
        (self.source / "VERSION").write_text("0.1.0-preview.1\n")
        self.output = self.root / "output"

    def portable(self):
        return build_release.build(self.output, source_dir=self.source, with_deb=False, epoch=0)

    def extract_portable(self, result):
        archive_path = next(Path(item["path"]) for item in result["artifacts"] if item["name"].endswith(".tar.gz"))
        extracted = self.root / "extracted"
        extracted.mkdir()
        with tarfile.open(archive_path) as archive:
            for member in archive.getmembers():
                self.assertFalse(member.issym() or member.islnk())
                self.assertTrue(member.isfile() or member.isdir())
                self.assertFalse(Path(member.name).is_absolute())
                self.assertNotIn("..", Path(member.name).parts)
            # All members above are already checked; use the standard safety
            # filter where available, including supported security backports.
            archive.extractall(extracted, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        return extracted / ("felix-pairing-" + result["version"])

    def assert_empty_home_can_inspect(self, package):
        home = self.root / "empty-home"
        home.mkdir(exist_ok=True)
        script = ("import json; from pathlib import Path; from backend import PairingService; "
                  "print(json.dumps(PairingService(home=Path(__import__('sys').argv[1]),system_dirs=[]).inspect()))")
        result = subprocess.run([sys.executable, "-B", "-c", script, str(home)], cwd=package,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertFalse(status["ready"])
        self.assertFalse(status["managed"])
        self.assertFalse((home / ".local/state/felix-pairing-tool").exists())

    def test_portable_contains_only_allowlisted_sources_and_matching_manifest(self):
        (self.source / "active.json").write_text('{"token":"fixture-never-package"}')
        (self.source / "private.log").write_text("fixture-never-package")
        result = self.portable()
        package = self.extract_portable(result)
        files = {file.relative_to(package).as_posix() for file in package.rglob("*") if file.is_file()}
        self.assertEqual(files, set(build_release.SOURCE_FILES) | {"BUILDINFO.json"})
        manifest = json.loads((package / "BUILDINFO.json").read_text())
        self.assertEqual(manifest["version"], "0.1.0-preview.1")
        self.assertEqual(set(manifest["source_files"]), set(build_release.SOURCE_FILES))
        self.assertNotIn(str(self.root), json.dumps(manifest))
        for name, digest in manifest["source_files"].items():
            self.assertEqual(hashlib.sha256((package / name).read_bytes()).hexdigest(), digest)
        self.assertEqual((package / "BUILDINFO.json").read_bytes(), (self.output / "BUILDINFO.json").read_bytes())
        self.assert_empty_home_can_inspect(package)

    def test_portable_rebuilds_identically_from_extracted_distribution(self):
        first = self.portable()
        package = self.extract_portable(first)
        second_output = self.root / "rebuilt"
        result = subprocess.run([sys.executable, "-B", "build_release.py", "--no-deb",
                                 "--output-dir", str(second_output), "--source-date-epoch", "0"],
                                cwd=package, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        second = json.loads(result.stdout)
        self.assertEqual({item["name"]: item["sha256"] for item in first["artifacts"]},
                         {item["name"]: item["sha256"] for item in second["artifacts"]})

    def test_checksums_cover_all_public_outputs_except_themselves(self):
        result = self.portable()
        checksums = (self.output / "SHA256SUMS").read_text().splitlines()
        expected = {item["name"]: item["sha256"] for item in result["artifacts"] if item["name"] != "SHA256SUMS"}
        found = {}
        for line in checksums:
            digest, name = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), digest)
            found[name] = digest
        self.assertEqual(found, expected)

    def test_missing_or_symlinked_release_sources_are_rejected(self):
        target = self.source / "README.md"
        original = target.read_bytes()
        target.unlink()
        with self.assertRaisesRegex(build_release.BuildError, "Missing release source"):
            self.portable()
        outside = self.root / "outside.txt"
        outside.write_bytes(original)
        target.symlink_to(outside)
        with self.assertRaisesRegex(build_release.BuildError, "symlinks"):
            self.portable()
        self.assertFalse(self.output.exists())

    def test_unsafe_output_and_invalid_version_are_rejected(self):
        actual = self.root / "actual-output"
        actual.mkdir()
        self.output.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(build_release.BuildError, "Output directory"):
            self.portable()
        self.output.unlink()
        (self.source / "VERSION").write_text("0.1.0; arbitrary-command\n")
        with self.assertRaisesRegex(build_release.BuildError, "VERSION"):
            self.portable()
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not installed")
    def test_deb_contents_dependencies_and_repeat_build_are_verified_without_installing(self):
        first = build_release.build(self.output, source_dir=self.source, epoch=0)
        first_deb = next(Path(item["path"]) for item in first["artifacts"] if item["name"].endswith(".deb"))
        control = subprocess.check_output(["dpkg-deb", "-f", str(first_deb)], text=True)
        self.assertIn("Package: felix-pairing\n", control)
        self.assertIn("Version: 0.1.0~preview1\n", control)
        self.assertIn("Architecture: all\n", control)
        self.assertIn("gir1.2-gtk-4.0 (>= 4.10)", control)
        self.assertIn("gir1.2-adw-1 (>= 1.4)", control)
        unpacked = self.root / "deb-unpacked"
        subprocess.run(["dpkg-deb", "-x", str(first_deb), str(unpacked)], check=True)
        controls = self.root / "deb-control"
        subprocess.run(["dpkg-deb", "-e", str(first_deb), str(controls)], check=True)
        self.assertEqual({path.name for path in controls.iterdir()}, {"control", "md5sums"})
        package = unpacked / "usr/share/felix-pairing-tool"
        self.assert_empty_home_can_inspect(package)
        icon = unpacked / "usr/share/icons/hicolor/scalable/apps/felix-pairing-round-v5.svg"
        self.assertEqual(icon.read_bytes(), (self.source / build_release.ICON_FILE).read_bytes())
        entry = unpacked / "usr/share/applications/io.github.felixproton.Pairing.desktop"
        self.assertIn("Icon=felix-pairing-round-v5\n", entry.read_text())
        launcher = unpacked / "usr/bin/felix-pairing"
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertNotIn("steam.desktop", {path.name for path in (unpacked / "usr/share/applications").iterdir()})
        second = build_release.build(self.root / "second-output", source_dir=self.source, epoch=0)
        self.assertEqual({item["name"]: item["sha256"] for item in first["artifacts"]},
                         {item["name"]: item["sha256"] for item in second["artifacts"]})


if __name__ == "__main__":
    unittest.main()
