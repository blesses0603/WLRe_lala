"""Isolated regression tests for the offline repository integrity auditor."""
import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tools import audit_repository


class AuditFixtures(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "docs").mkdir()
        (self.root / "wlre").mkdir()
        (self.root / "README.md").write_text(
            "# Home\n[guide](docs/guide.md)\n[fragment](#home)\n"
            "[remote](https://example.org/path)\n", encoding="utf-8")
        (self.root / "版本歷史.md").write_text(
            "[home](README.md#home)\n", encoding="utf-8")
        (self.root / "docs/guide.md").write_text(
            "[home](../README.md)\n", encoding="utf-8")
        (self.root / "wlre/__init__.py").write_text(
            '__version__ = "0.5.0"\n', encoding="utf-8")

    def test_links_skip_external_urls_and_support_fragments(self):
        asset = self.root / "wlre/resources/assets/buttons"
        asset.mkdir(parents=True)
        (asset / "SOURCE.md").write_text("[main](../../../../README.md)\n", encoding="utf-8")
        self.assertIn(asset / "SOURCE.md", audit_repository.markdown_files(self.root))
        count, broken = audit_repository.invalid_links(self.root)
        self.assertEqual(count, 4)
        self.assertEqual(broken, [])

    def test_missing_and_outside_links_are_reported(self):
        (self.root / "docs/guide.md").write_text(
            "[gone](missing.md)\n[outside](../../private.txt)\n", encoding="utf-8")
        count, broken = audit_repository.invalid_links(self.root)
        self.assertEqual(count, 4)
        self.assertEqual(len(broken), 2)
        self.assertTrue(any("missing.md" in item for item in broken))
        self.assertTrue(any("../../private.txt" in item for item in broken))

    def test_version_quotes_and_missing_version(self):
        self.assertEqual(audit_repository.application_version(self.root), "0.5.0")
        (self.root / "wlre/__init__.py").write_text(
            "__version__ = '0.6.0'\n", encoding="utf-8")
        self.assertEqual(audit_repository.application_version(self.root), "0.6.0")
        (self.root / "wlre/__init__.py").write_text(
            "VERSION = '0.6.0'\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            audit_repository.application_version(self.root)

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_duplicate_nonempty_blobs_but_not_empty_init_files(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "a.txt").write_bytes(b"same nonempty payload")
        (self.root / "b.txt").write_bytes(b"same nonempty payload")
        (self.root / "tools").mkdir()
        (self.root / "tools/__init__.py").write_bytes(b"")
        (self.root / "wlre/__init__.py").write_bytes(b"")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        self.assertEqual(audit_repository.duplicate_tracked_blobs(self.root),
                         [["a.txt", "b.txt"]])

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_official_1275_binary_sources_cannot_remain_tracked(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        private = self.root / "1275_差異"
        private.mkdir()
        (private / "LaLa_1275_差異選取清單.json").write_text("{}", encoding="utf-8")
        (private / "unity default resources").write_bytes(b"synthetic fixture, not game data")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        self.assertEqual(audit_repository.tracked_private_game_assets(self.root),
                         ["1275_差異/unity default resources"])
        subprocess.run(["git", "rm", "--cached", "--", "1275_差異/unity default resources"],
                       cwd=self.root, capture_output=True, check=True)
        self.assertEqual(audit_repository.tracked_private_game_assets(self.root), [])

    def test_no_git_index_does_not_masquerade_as_a_pass(self):
        self.assertIsNone(audit_repository.duplicate_tracked_blobs(self.root))
        result = audit_repository.audit(self.root)
        self.assertFalse(result["git_index_available"])
        self.assertIsNone(result["nonempty_duplicate_blobs"])

    def test_strict_git_and_broken_links_produce_failure_exit_codes(self):
        no_index = {"broken_local_links": [], "nonempty_duplicate_blobs": None,
                    "private_official_game_assets_tracked": None, "git_index_available": False}
        bad_link = {"broken_local_links": ["broken.md"], "nonempty_duplicate_blobs": [],
                    "private_official_game_assets_tracked": [], "git_index_available": True}
        with patch.object(audit_repository, "audit", return_value=no_index):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(audit_repository.main([]), 0)
                self.assertEqual(audit_repository.main(["--strict-git"]), 1)
        with patch.object(audit_repository, "audit", return_value=bad_link):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(audit_repository.main([]), 1)


if __name__ == "__main__":
    unittest.main()
