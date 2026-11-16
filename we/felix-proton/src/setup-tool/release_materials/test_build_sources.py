# SPDX-License-Identifier: BSD-3-Clause
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import build_sources


class SourceMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory(prefix="felix-source-tests-"))
        self.root = Path(self.temp)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.payload = b"source bytes kept unchanged\n"
        self.name = "example-0123456789abcdef.tar.gz"
        (self.cache / self.name).write_bytes(self.payload)
        self.entry = {"component": "example", "revision": "0123456789abcdef", "file": self.name,
                      "url": "https://example.invalid/source.tar.gz", "bytes": len(self.payload),
                      "sha256": hashlib.sha256(self.payload).hexdigest()}
        self.lock = {"schema": "felix-runtime-dependency-sources-v1", "archives": [self.entry]}
        self.lock_path = self.root / "lock.json"
        self.save()

    def save(self):
        self.lock_path.write_text(json.dumps(self.lock))

    def test_invalid_or_duplicate_names_and_unpinned_materials_are_rejected(self):
        for field, value in [("file", "../escape.tar.gz"), ("sha256", ""), ("bytes", 0),
                             ("revision", ""), ("url", "http://example.invalid/file"),
                             ("url", "https://user:password@example.invalid/file")]:
            with self.subTest(field=field, value=value):
                self.lock["archives"] = [dict(self.entry, **{field: value})]
                self.save()
                with self.assertRaises(build_sources.SourceError):
                    build_sources.load_lock(self.lock_path)
        self.lock["archives"] = [self.entry, self.entry]
        self.save()
        with self.assertRaises(build_sources.SourceError):
            build_sources.load_lock(self.lock_path)

    def test_changed_or_symlinked_cache_files_fail_before_publication(self):
        p = self.cache / self.name
        p.write_bytes(b"changed")
        with self.assertRaisesRegex(build_sources.SourceError, "checksum"):
            build_sources.build(self.cache, self.root / "out", self.lock_path)
        self.assertFalse((self.root / "out").exists())
        target = self.root / "outside"
        target.write_bytes(self.payload)
        p.unlink()
        p.symlink_to(target)
        with self.assertRaisesRegex(build_sources.SourceError, "regular"):
            build_sources.build(self.cache, self.root / "out", self.lock_path)
        self.assertEqual(target.read_bytes(), self.payload)

    def test_failed_download_keeps_cache_clean_and_existing_sources_unchanged(self):
        (self.cache / self.name).unlink()
        with patch("build_sources.urllib.request.urlopen", return_value=io.BytesIO(b"wrong")):
            with self.assertRaisesRegex(build_sources.SourceError, "checksum"):
                build_sources.fetch(self.cache, self.lock)
        self.assertEqual(list(self.cache.iterdir()), [])
        with patch("build_sources.urllib.request.urlopen", return_value=io.BytesIO(self.payload)):
            build_sources.fetch(self.cache, self.lock)
        with patch("build_sources.urllib.request.urlopen", side_effect=AssertionError("must reuse verified input")):
            build_sources.fetch(self.cache, self.lock)
        self.assertEqual((self.cache / self.name).read_bytes(), self.payload)

    @unittest.skipUnless(shutil.which("zstd"), "zstd not installed")
    def test_reproducible_bundle_carries_original_bytes_checksums_and_notices(self):
        first = build_sources.build(self.cache, self.root / "one", self.lock_path)
        second = build_sources.build(self.cache, self.root / "two", self.lock_path)
        self.assertEqual(first, second)
        archive = self.root / "one" / build_sources.BUNDLE
        decoded = subprocess.check_output(["zstd", "-dq", "-c", str(archive)])
        with tarfile.open(fileobj=io.BytesIO(decoded), mode="r:") as tar:
            prefix = build_sources.TOP + "/"
            self.assertEqual(set(tar.getnames()), {prefix + name for name in (
                "SOURCE_LOCK.json", "THIRD_PARTY_NOTICES.md", "README.md", "SHA256SUMS", "archives/" + self.name)})
            self.assertTrue(all(member.uid == 0 and member.gid == 0 and member.mtime == 0 for member in tar))
            self.assertEqual(tar.extractfile(prefix + "archives/" + self.name).read(), self.payload)
            self.assertIn(self.entry["sha256"].encode(), tar.extractfile(prefix + "SHA256SUMS").read())
            self.assertIn(b"SHORiN-KiWATA", tar.extractfile(prefix + "THIRD_PARTY_NOTICES.md").read())
        index = json.loads((self.root / "one/SOURCE_INDEX.json").read_text())
        self.assertEqual(index["dependency_bundle"]["sha256"], build_sources.digest(archive))
        self.assertNotIn(str(self.root), json.dumps(index))
        self.assertEqual((self.cache / self.name).read_bytes(), self.payload)
        with self.assertRaisesRegex(build_sources.SourceError, "overwrite"):
            build_sources.build(self.cache, self.root / "one", self.lock_path)


if __name__ == "__main__":
    unittest.main()
