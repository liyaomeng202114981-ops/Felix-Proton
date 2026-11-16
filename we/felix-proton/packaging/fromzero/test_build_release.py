# SPDX-License-Identifier: BSD-3-Clause
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("setup_release", Path(__file__).with_name("build_release.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.names = ["src/setup-tool/setup.py", "src/setup-tool/downloads.json",
                      "src/native-ux/enable.py", "src/pairing-tool/app.py",
                      "src/pairing-tool/lib/desktop.py", "src/native-ux/desktop.py",
                      "src/native-ux/LICENSE", "packaging/fromzero/INSTALL.md"]
        for name in self.names:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"public-source\n")
        self.inventory = self.base / "inventory.json"
        self.inventory.write_text(json.dumps(self.names))

    def test_archive_hashes_and_repeat_build_exclude_unlisted_private_state(self):
        private = self.source / "pfx" / "user.reg"
        private.parent.mkdir()
        private.write_text("private-account-fixture")
        first = release.build(self.source, self.inventory, self.base / "one")
        second = release.build(self.source, self.inventory, self.base / "two")
        self.assertEqual(first, second)
        archive = self.base / "one" / first["archive"]
        with tarfile.open(archive) as package:
            prefix = release.KIT + "/"
            self.assertEqual(set(package.getnames()), {prefix + n for n in self.names + ["README.md", "LICENSE", "BUILDINFO.json"]})
            manifest = json.load(package.extractfile(prefix + "BUILDINFO.json"))
            for name, sha in manifest["source_files"].items():
                self.assertEqual(hashlib.sha256(package.extractfile(prefix + name).read()).hexdigest(), sha)
        release.checksums(self.base / "one")
        self.assertIn(first["sha256"] + "  " + first["archive"], (self.base / "one/SHA256SUMS").read_text())

    def test_escape_symlink_and_missing_canonical_source_are_rejected(self):
        for invalid in ("../account.json", "/absolute", "src/evidence/token.json", "src/file.log"):
            with self.subTest(invalid=invalid):
                self.inventory.write_text(json.dumps(self.names + [invalid]))
                with self.assertRaises(ValueError):
                    release.read_sources(self.source, self.inventory)
        self.inventory.write_text(json.dumps(self.names))
        target = self.source / self.names[0]
        target.unlink()
        target.symlink_to(self.source / "src/native-ux/enable.py")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            release.read_sources(self.source, self.inventory)


if __name__ == "__main__":
    unittest.main()
