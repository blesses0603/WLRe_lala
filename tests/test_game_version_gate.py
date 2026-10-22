"""No game account, network or Unity installation required."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wlre.services.game_version_gate import (
    find_yoo_root, run_prelogin_check, scan_local_manifests,
)


def paired(folder, package, version, stamp="2026_10_21_18_29_38_49"):
    for suffix in ("bytes", "hash"):
        (folder / f"{package}_{version}_{stamp}.{suffix}").write_bytes(b"x")


class LocalGameVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "SampleGame_Data" / "yoo"
        for name in ("MainPackage", "DataPackage"):
            (self.root / name / "ManifestFiles").mkdir(parents=True)

    def test_1262_is_local_match_not_official_verified(self):
        for name in ("MainPackage", "DataPackage"):
            paired(self.root / name / "ManifestFiles", name, "1262")
        with patch("wlre.services.game_version_gate.check_official_versions") as check:
            check.return_value = {"status": "unverified", "packages": {}}
            result = run_prelogin_check(self.root)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["local"]["status"], "same_local")

    def test_1275_blocks_even_if_offline(self):
        paired(self.root / "MainPackage" / "ManifestFiles", "MainPackage", "1262")
        paired(self.root / "DataPackage" / "ManifestFiles", "DataPackage", "1275")
        with patch("wlre.services.game_version_gate.check_official_versions") as check:
            check.return_value = {"status": "unverified", "packages": {}}
            result = run_prelogin_check(self.root)
        self.assertTrue(result["blocked"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("禁止登入", result["message"])

    def test_newest_complete_pair_selected_and_older_cache_ignored(self):
        folder = self.root / "MainPackage" / "ManifestFiles"
        paired(folder, "MainPackage", "1076")
        paired(folder, "MainPackage", "1262")
        paired(self.root / "DataPackage" / "ManifestFiles", "DataPackage", "1262")
        self.assertEqual(scan_local_manifests(self.root)["status"], "same_local")
        paired(folder, "MainPackage", "1275")
        self.assertEqual(scan_local_manifests(self.root)["status"], "changed")
        self.assertEqual(scan_local_manifests(self.root)["packages"]["MainPackage"]["version"], "1275")

    def test_incomplete_manifest_not_claimed(self):
        path = self.root / "MainPackage" / "ManifestFiles" / "MainPackage_1275_2026_10_21_18_29_38_49.bytes"
        path.touch()
        paired(self.root / "DataPackage" / "ManifestFiles", "DataPackage", "1262")
        result = scan_local_manifests(self.root)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["packages"]["MainPackage"]["status"], "unverified")

    def test_missing_root_not_claimed(self):
        self.assertIsNone(find_yoo_root(Path(self.temp.name) / "missing", strict=True))
        with patch("wlre.services.game_version_gate.find_yoo_root", return_value=None):
            self.assertEqual(scan_local_manifests()["status"], "unverified")

    def test_game_install_parent_autodiscovered(self):
        paired(self.root / "MainPackage" / "ManifestFiles", "MainPackage", "1262")
        paired(self.root / "DataPackage" / "ManifestFiles", "DataPackage", "1262")
        self.assertEqual(find_yoo_root(self.root.parent.parent, strict=True), self.root)

    def test_confirmed_remote_delta_blocks_even_if_one_source_unavailable(self):
        with patch("wlre.services.game_version_gate.check_official_versions") as check:
            check.return_value = {
                "status": "unverified",
                "packages": {"MainPackage": {"comparison": "newer", "remote": "1275"},
                             "DataPackage": {"comparison": "unverified"}}
            }
            result = run_prelogin_check(self.root)
        self.assertTrue(result["blocked"])

    def test_remote_match_never_claims_protocol_compatibility(self):
        for name in ("MainPackage", "DataPackage"):
            paired(self.root / name / "ManifestFiles", name, "1262")
        with patch("wlre.services.game_version_gate.check_official_versions") as check:
            check.return_value = {"status": "same_resources", "packages": {},
                                  "protocol_compatibility": "unverified"}
            result = run_prelogin_check(self.root)
        self.assertEqual(result["status"], "version_identifiers_match")
        self.assertEqual(result["remote"]["protocol_compatibility"], "unverified")


if __name__ == "__main__":
    unittest.main()
