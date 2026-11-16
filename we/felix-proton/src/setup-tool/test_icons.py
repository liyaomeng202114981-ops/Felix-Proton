# SPDX-License-Identifier: BSD-3-Clause
"""Synthetic PE resource checks, not vendor executables or account data."""
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

import icons

# A one-pixel fixture, not a third-party brand resource.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg==")


def pe_fixture():
    image = bytearray(0xA00)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 60, 0x80)
    image[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", image, 0x84, 0x14C, 1)
    struct.pack_into("<HH", image, 0x94, 0xE0, 2)
    optional = 0x98
    struct.pack_into("<H", image, optional, 0x10B)
    struct.pack_into("<I", image, optional + 92, 16)
    struct.pack_into("<II", image, optional + 112, 0x1000, 0x600)
    section = optional + 0xE0
    image[section:section + 8] = b".rsrc\0\0\0"
    struct.pack_into("<IIII", image, section + 8, 0x600, 0x1000, 0x600, 0x200)
    def directory(offset, entries):
        struct.pack_into("<HH", image, 0x200 + offset + 12, 0, len(entries))
        for index, (key, child) in enumerate(entries):
            struct.pack_into("<II", image, 0x200 + offset + 16 + index * 8, key, child)
    directory(0, [(3, 0x80000020), (14, 0x80000050)])
    directory(0x20, [(1, 0x80000038)])
    directory(0x38, [(2052, 0x80)])
    directory(0x50, [(107, 0x80000068)])
    directory(0x68, [(2052, 0x90)])
    struct.pack_into("<II", image, 0x280, 0x1100, len(PNG))
    struct.pack_into("<II", image, 0x290, 0x10A0, 20)
    group = struct.pack("<HHHBBBBHHIH", 0, 1, 1, 1, 1, 0, 0, 1, 32, len(PNG), 1)
    image[0x2A0:0x2A0 + len(group)] = group
    image[0x300:0x300 + len(PNG)] = PNG
    return bytes(image)


class IconTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="felix-icon-test-")))
        self.exe = self.root / "fixture.exe"
        self.exe.write_bytes(pe_fixture())

    def test_resources_become_standard_ico_without_executing_the_exe(self):
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("no client execution")):
            ico, digest = icons.extract_ico(self.exe)
        self.assertEqual(digest, hashlib.sha256(pe_fixture()).hexdigest())
        self.assertEqual(struct.unpack_from("<HHH", ico), (0, 1, 1))
        self.assertEqual(struct.unpack_from("<II", ico, 14), (len(PNG), 22))
        self.assertEqual(ico[22:], PNG)

    def test_truncation_and_resource_directory_escape_are_rejected(self):
        for bad in (b"MZ", pe_fixture()[:0x305]):
            with self.assertRaises(icons.IconError):
                icons.PEIcons(bad).ico()
        bad = bytearray(pe_fixture())
        struct.pack_into("<I", bad, 0x214, 0xFFFFFFFF)
        with self.assertRaises(icons.IconError):
            icons.PEIcons(bad).ico()

    def test_group_bounds_and_referenced_image_size_are_checked(self):
        for offset, value in ((0x2A4, 129), (0x2AA, 1)):
            bad = bytearray(pe_fixture())
            if offset == 0x2A4:
                struct.pack_into("<H", bad, offset, value)
            else:
                struct.pack_into("<I", bad, 0x2AE, len(PNG) + 1)
            with self.assertRaises(icons.IconError):
                icons.PEIcons(bad).ico()

    def test_ambiguous_rva_and_non_regular_or_symlink_input_are_refused(self):
        bad = bytearray(pe_fixture())
        struct.pack_into("<H", bad, 0x86, 2)
        section = 0x178
        bad[section + 40:section + 80] = bad[section:section + 40]
        with self.assertRaises(icons.IconError):
            icons.PEIcons(bad)
        link = self.root / "link.exe"
        link.symlink_to(self.exe)
        with self.assertRaises(OSError):
            icons.extract_ico(link)
        with self.assertRaises(icons.IconError):
            icons.extract_ico(self.root)

    def test_icon_publication_and_repeat_reuse_keep_source_and_external_edits(self):
        before = self.exe.read_bytes()
        def decode(argv, **kwargs):
            self.assertEqual(argv[:2], ["/usr/bin/python3", "-B"])
            self.assertEqual(argv[-3], "--decode")
            Path(argv[-1]).write_bytes(PNG)
            return subprocess.CompletedProcess(argv, 0)
        with mock.patch.object(icons.subprocess, "run", side_effect=decode) as child:
            target = icons.install_icon(self.exe, self.root / "data")
            self.assertEqual(icons.install_icon(self.exe, self.root / "data"), target)
        child.assert_called_once()
        self.assertEqual(self.exe.read_bytes(), before)
        self.assertEqual(target.read_bytes(), PNG)
        data = json.loads(target.with_name("source.json").read_text())
        self.assertEqual(data["owner"], icons.OWNER)
        target.write_bytes(PNG + b"personal edit")
        with self.assertRaises(icons.IconError):
            icons.install_icon(self.exe, self.root / "data")
        self.assertTrue(target.read_bytes().endswith(b"personal edit"))

    def test_decode_failure_does_not_publish_a_final_icon_directory(self):
        with mock.patch.object(icons.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(icons.IconError):
                icons.install_icon(self.exe, self.root / "data")
        base = self.root / "data/felix-proton-setup/icons-v1"
        self.assertEqual(list(base.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
