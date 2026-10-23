"""Bundled resource baseline is the sole source of local support evidence."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wlre.services.resource_compatibility import (
    PACKAGES, ResourceBaselineError, baseline_label, baseline_maps,
    load_supported_resources,
)
from wlre.services import game_version_gate, official_version


def fake_config(main_revision="1262", data_revision="1262"):
    return {
        "schema_version": 1,
        "official_game_exe_version": "1.3.0",
        "packages": {
            "MainPackage": {
                "revision": main_revision,
                "manifest": f"{main_revision}_2026_10_14_15_02_22_47",
            },
            "DataPackage": {
                "revision": data_revision,
                "manifest": f"{data_revision}_2026_10_14_15_00_34_84",
            },
        },
    }


class BundledResourceCompatibilityTests(unittest.TestCase):
    def test_real_bundled_file_derives_official_gate_baseline(self):
        data = load_supported_resources()
        numbers, full = baseline_maps(data)
        self.assertEqual(numbers, official_version.BASELINE)
        self.assertEqual(full, official_version.BASELINE_MANIFEST)
        self.assertEqual(data["official_game_exe_version"],
                         official_version.SUPPORTED_OFFICIAL_EXE_VERSION)
        self.assertEqual(baseline_label(numbers), "1275")
        for package in PACKAGES:
            self.assertTrue(full[package].startswith(numbers[package] + "_"))

    def test_future_release_changes_display_and_comparison_without_text_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lala_supported_resources.json"
            payload = fake_config(main_revision="1275", data_revision="1275")
            path.write_text(json.dumps(payload), encoding="utf-8")
            data = load_supported_resources(path)
        revisions, manifests = baseline_maps(data)
        self.assertEqual(baseline_label(revisions), "1275")

        # Patch the same imported baseline maps to simulate a newly shipped
        # LaLa build, NOT a remote official update changing LaLa's baseline.
        with patch.dict(official_version.BASELINE, revisions, clear=True), \
                patch.dict(official_version.BASELINE_MANIFEST, manifests, clear=True):
            sources = official_version.official_package_urls("1.3.21")
            checked = official_version.check_official_versions(
                sources, strict_manifest=True,
                fetcher=lambda url: manifests[
                    "MainPackage" if "MainPackage" in url else "DataPackage"])
            self.assertEqual(checked["status"], "same_resources")
            with patch("wlre.services.game_version_gate.check_official_game_resources",
                       return_value=checked), patch(
                           "wlre.services.world.runtime_1275.ready",
                           return_value=(True, "1275 fixture verified")):
                matched = game_version_gate.run_prelogin_check()
            self.assertFalse(matched["blocked"])
            self.assertIn("1275", matched["message"])
            self.assertNotIn("1262", matched["message"])

            changed = official_version.check_official_versions(
                sources, strict_manifest=True,
                fetcher=lambda url: "1280_2026_10_23_15_00_00_00")
            self.assertEqual(changed["status"], "resources_changed")
            with patch("wlre.services.game_version_gate.check_official_game_resources",
                       return_value=changed):
                blocked = game_version_gate.run_prelogin_check()
            self.assertTrue(blocked["blocked"])
            self.assertIn("1275", blocked["message"])
            self.assertNotIn("1262", blocked["message"])

    def test_different_supported_revisions_are_not_collapsed(self):
        document = fake_config("1262", "1275")
        numbers, full = baseline_maps(document)
        label = baseline_label(numbers)
        self.assertIn("DataPackage 1275", label)
        self.assertIn("MainPackage 1262", label)
        self.assertNotEqual(full["DataPackage"], full["MainPackage"])
        with patch.dict(official_version.BASELINE, numbers, clear=True), \
                patch.dict(official_version.BASELINE_MANIFEST, full, clear=True):
            result = official_version.check_official_versions(
                official_version.official_package_urls("1.3.21"),
                strict_manifest=True,
                fetcher=lambda url: full[
                    "DataPackage" if "DataPackage" in url else "MainPackage"])
            self.assertEqual(result["status"], "same_resources")
            with patch("wlre.services.game_version_gate.check_official_game_resources",
                       return_value=result):
                checked = game_version_gate.run_prelogin_check()
            self.assertEqual(checked["baseline_label"], label)
            self.assertIn("DataPackage 1275", checked["message"])

    def test_invalid_or_missing_internal_baseline_must_raise(self):
        samples = [
            {"schema_version": 1, "official_game_exe_version": "1.3.0",
             "packages": {}},
            fake_config(main_revision="1275"),
            fake_config(main_revision="1262"),
            fake_config(main_revision="1262", data_revision="0"),
            fake_config(),
        ]
        samples[1]["packages"]["MainPackage"]["manifest"] = "1262_2026_10_14_15_02_22_47"
        samples[2]["packages"]["DataPackage"]["manifest"] = "../invalid"
        samples[-1]["official_game_exe_version"] = "not-a-version"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.json"
            with self.assertRaises(ResourceBaselineError):
                load_supported_resources(path)
            for sample in samples:
                with self.subTest(payload=sample):
                    path.write_text(json.dumps(sample), encoding="utf-8")
                    with self.assertRaises(ResourceBaselineError):
                        load_supported_resources(path)
            path.write_text("{}" * 3000, encoding="utf-8")
            with self.assertRaises(ResourceBaselineError):
                load_supported_resources(path)

    def test_packager_requires_compatibility_json(self):
        from wlre.resource_manifest import REQUIRED_RESOURCES, data_files
        from wlre.paths import PACKAGE_ROOT
        self.assertIn("lala_supported_resources.json", REQUIRED_RESOURCES)
        filenames = [str(p) for p in data_files(PACKAGE_ROOT)]
        self.assertTrue(any(n.endswith("lala_supported_resources.json")
                            for n in filenames))


if __name__ == "__main__":
    unittest.main()
