# SPDX-License-Identifier: BSD-3-Clause
"""Application import must never evaluate dropped desktop-file contents."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import catalog


class Info:
    def __init__(self, desktop_id, filename, name="Steam", icon=None, shown=True):
        self.desktop_id, self.filename, self.name = desktop_id, str(filename), name
        self.icon, self.shown = icon, shown
    def get_id(self): return self.desktop_id
    def get_filename(self): return self.filename
    def get_display_name(self): return self.name
    def get_icon(self): return self.icon
    def should_show(self): return self.shown


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.steam = self.root / "steam.desktop"
        self.uu = self.root / "uu-accelerator.desktop"
        # These strings are inert fixtures. No test launches or parses Exec.
        self.steam.write_text("Exec=do-not-run\n")
        self.uu.write_text("Exec=do-not-run-either\n")
        self.icon = object()
        self.entries = [Info("steam.desktop", self.steam, icon=self.icon),
                        Info("uu-accelerator.desktop", self.uu, "网易 UU")]
        self.enterContext(patch.object(catalog, "_inventory", side_effect=lambda:self.entries))

    def test_exact_ids_only_and_original_metadata_is_retained(self):
        self.entries.append(Info("renamed.desktop", self.steam, "Steam"))
        apps = catalog.load_apps()
        self.assertEqual([app.desktop_id for app in apps], ["steam.desktop", "uu-accelerator.desktop"])
        self.assertEqual([app.kind for app in apps], ["platform", "accelerator"])
        self.assertTrue(all(app.supported for app in apps))
        self.assertIs(apps[0].icon, self.icon)
        self.assertEqual(catalog.classify("renamed.desktop", "steam"), None)

    def test_internal_and_application_uris_resolve_installed_ids(self):
        for value in ("felix-app:steam.desktop", "application://steam.desktop"):
            self.assertEqual(catalog.resolve_drop(value).filename, str(self.steam))
        self.assertEqual(catalog.resolve_drop("felix-app:uu-accelerator.desktop").kind, "accelerator")

    def test_file_uris_and_local_paths_match_actual_installed_entry(self):
        for value in (str(self.steam), self.steam.as_uri(), "file://localhost" + str(self.steam)):
            self.assertEqual(catalog.resolve_drop(value).desktop_id, "steam.desktop")

    def test_fake_same_filename_and_names_are_refused(self):
        fake = self.root / "Downloads" / "steam.desktop"
        fake.parent.mkdir()
        fake.write_text(self.steam.read_text())
        with self.assertRaisesRegex(ValueError, "不是当前已安装"):
            catalog.resolve_drop(str(fake))
        with self.assertRaisesRegex(ValueError, "首版只支持"):
            catalog.resolve_drop("felix-app:fake-steam.desktop")

    def test_external_multiple_and_malformed_drops_are_refused(self):
        values = ("https://example.com/steam.desktop", "file://example.com" + str(self.steam),
                  self.steam.as_uri()+"\n"+self.uu.as_uri(), "application://steam.desktop?run=1",
                  "felix-app:../steam.desktop", self.steam.as_uri()+"?run=1", "steam.desktop",
                  "file:///tmp/%0Asteam.desktop", None)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                catalog.resolve_drop(value)

    def test_hidden_removed_and_nonfile_entries_are_not_imported(self):
        self.entries[0].shown = False
        self.uu.unlink()
        self.assertEqual(catalog.load_apps(), [])
        with self.assertRaisesRegex(ValueError, "未找到"):
            catalog.resolve_drop("application://steam.desktop")

    def test_effective_entry_symlink_refers_to_same_installed_file(self):
        link = self.root / "original.desktop"
        link.symlink_to(self.steam)
        self.assertEqual(catalog.resolve_drop(str(link)).desktop_id, "steam.desktop")


if __name__ == "__main__":
    unittest.main()
