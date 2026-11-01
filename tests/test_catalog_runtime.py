"""Regression checks for fail-closed version-neutral catalog selection."""
import unittest

from wlre.services.world.catalog_runtime import select_catalog_runtime


class CatalogRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.key = "a" * 64
        self.remote = {
            "resource_path": "1.3.21", "official_exe_version": "1.3.0",
            "newer_official_client": False,
            "packages": {
                "DataPackage": {"remote": "1286_2026_10_29_13_42_37_94"},
                "MainPackage": {"remote": "1284_2026_10_28_12_00_00_00"},
            },
        }
        self.candidate = {
            "catalog_key": self.key,
            "official_identity": {
                "data_ver": "1.3.21", "exe_version": "1.3.0",
                "packages": [
                    {"name": "DataPackage", "full_version": "1286_2026_10_29_13_42_37_94"},
                    {"name": "MainPackage", "full_version": "1284_2026_10_28_12_00_00_00"},
                ],
            },
            "status": "review_required", "approved": False,
            "assets_ready": False, "can_send_packets": False,
            "features": {name: {"sha256": "b" * 64}
                         for name in ("npc", "shops", "crafting", "scenes")},
        }

    def test_different_package_revisions_still_match(self):
        result = select_catalog_runtime(self.remote, self.candidate)
        self.assertEqual(result.status, "review_required")
        self.assertFalse(result.can_send_packets)

    def test_release_review_does_not_approve_protocol(self):
        result = select_catalog_runtime(
            self.remote, self.candidate, reviewed_keys=(self.key,))
        self.assertEqual(result.status, "reviewed_source")
        self.assertFalse(result.assets_ready)
        self.assertFalse(result.can_send_packets)

    def test_mismatched_official_revision_blocks(self):
        self.remote["packages"]["MainPackage"]["remote"] = "1290"
        self.assertEqual(
            select_catalog_runtime(self.remote, self.candidate).status, "blocked")

    def test_missing_feature_blocks(self):
        del self.candidate["features"]["npc"]
        self.assertEqual(
            select_catalog_runtime(self.remote, self.candidate).reason,
            "incomplete_features")

    def test_candidate_cannot_self_approve(self):
        self.candidate["approved"] = True
        self.assertEqual(
            select_catalog_runtime(self.remote, self.candidate).status, "blocked")


if __name__ == "__main__":
    unittest.main()
