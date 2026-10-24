"""1275 game file inventory: no mutation and explicit bundle-copy opt-in."""
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from tools.resources.inventory_1275_bundles import InventoryError, collect, inventory


class Inventory1275Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "yoo"
        for package in ("DataPackage", "MainPackage"):
            manifest = self.root / package / "ManifestFiles"
            manifest.mkdir(parents=True)
            (manifest / (package + "_1275_2026_10_21_18_27_33_84.bytes")).write_bytes(b"manifest")
            (manifest / (package + "_1275_2026_10_21_18_27_33_84.hash")).write_bytes(b"12345678")
            bundle = self.root / package / "BundleFiles" / "00" / "mock"
            bundle.mkdir(parents=True)
            (bundle / "__data").write_bytes(package.encode())

    def test_inventory_omits_unrelated_files_and_reports_hashes(self):
        data = inventory(self.root)
        self.assertEqual(data["revision"], "1275")
        self.assertEqual(data["bundle_count"], 2)
        self.assertEqual(data["file_count"], 6)
        self.assertTrue(all(len(x["sha256"]) == 64 for x in data["files"]))

    def test_default_archive_contains_manifest_and_inventory_but_not_bundles(self):
        target = Path(self.tmp.name) / "inventory.zip"
        original = (self.root / "MainPackage/BundleFiles/00/mock/__data").read_bytes()
        collect(self.root, target)
        with ZipFile(target) as z:
            names = z.namelist()
            self.assertEqual(len(names), 5)
            self.assertFalse(any("/BundleFiles/" in n for n in names))
            self.assertEqual(json.loads(z.read("inventory.json"))["bundle_count"], 2)
        self.assertEqual((self.root / "MainPackage/BundleFiles/00/mock/__data").read_bytes(), original)

    def test_bundle_copy_is_opt_in_and_never_overwrites(self):
        target = Path(self.tmp.name) / "with-bundles.zip"
        collect(self.root, target, include_bundles=True)
        with ZipFile(target) as z:
            self.assertEqual(len(z.namelist()), 7)
        with self.assertRaises(FileExistsError):
            collect(self.root, target, include_bundles=False)

    def _make_selection(self):
        rows = inventory(self.root)["files"]
        data = {"target_revision": 1275,
                "manifest_sha256_1275": {
                    package: next(r["sha256"] for r in rows
                                  if r["package"] == package and r["kind"] == "manifest")
                    for package in ("MainPackage", "DataPackage")},
                "bundles": []}
        for row in rows:
            if row["kind"] != "bundle":
                continue
            group = "data" if row["package"] == "DataPackage" else "ui"
            data["bundles"].append({
                **row, "group": group,
                "file_hash": row["path"].split("/")[-2]})
        target = Path(self.tmp.name) / "delta.json"
        target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return target

    def test_selection_copies_only_one_group_and_verifies_every_digest(self):
        selection = self._make_selection()
        target = Path(self.tmp.name) / "data-only.zip"
        result = collect(self.root, target, selection_file=selection, group="data")
        self.assertEqual(result["selected_bundles"], 1)
        self.assertTrue(result["included_bundle_bytes"])
        with ZipFile(target) as z:
            names = z.namelist()
            self.assertEqual(len(names), 6)
            self.assertTrue(any("DataPackage/BundleFiles" in n for n in names))
            self.assertFalse(any("MainPackage/BundleFiles" in n for n in names))

    def test_selection_refuses_wrong_manifest_and_tampered_hash(self):
        selection = self._make_selection()
        document = json.loads(selection.read_text(encoding="utf-8"))
        document["manifest_sha256_1275"]["MainPackage"] = "0" * 64
        selection.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(InventoryError):
            collect(self.root, Path(self.tmp.name) / "wrong-manifest.zip",
                    selection_file=selection)
        selection = self._make_selection()
        document = json.loads(selection.read_text(encoding="utf-8"))
        document["bundles"][0]["sha256"] = "0" * 64
        selection.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(InventoryError):
            collect(self.root, Path(self.tmp.name) / "tampered.zip",
                    selection_file=selection, group="data")

    def test_selection_and_full_archive_are_mutually_exclusive(self):
        selection = self._make_selection()
        with self.assertRaises(InventoryError):
            collect(self.root, Path(self.tmp.name) / "both.zip",
                    selection_file=selection, include_bundles=True)
        with self.assertRaises(InventoryError):
            collect(self.root, Path(self.tmp.name) / "no-selection.zip",
                    group="ui")

    def test_one_command_exports_all_selected_bundles_as_verified_zip_parts(self):
        # Larger fixture files force separate independent ZIP parts.
        for package in ("DataPackage", "MainPackage"):
            (self.root / package / "BundleFiles" / "00" / "mock" /
             "__data").write_bytes(package.encode().ljust(700 * 1024, b"X"))
        selection = self._make_selection()
        output = Path(self.tmp.name) / "all-1275.zip"
        result = collect(self.root, output, selection_file=selection, split_mib=1)
        self.assertEqual(result["selected_bundles"], 2)
        self.assertEqual(len(result["parts"]), 2)
        paths = [Path(row["output"]) for row in result["parts"]]
        self.assertEqual([p.name for p in paths],
                         ["all-1275.part01.zip", "all-1275.part02.zip"])
        seen = []
        for row in result["parts"]:
            p = Path(row["output"])
            self.assertLessEqual(p.stat().st_size, 1024 * 1024)
            with ZipFile(p) as z:
                self.assertIsNone(z.testzip())
                self.assertIn("inventory.json", z.namelist())
                part = json.loads(z.read("selection_part.json"))
                self.assertEqual(part["part_count"], 2)
                self.assertEqual(part["selected_bundle_count"], 1)
                seen.extend(part["paths"])
                for path in part["paths"]:
                    self.assertIn("source/" + path, z.namelist())
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(set(seen)), 2)

    def test_split_rejects_partial_overwrites_before_writing_any_part(self):
        selection = self._make_selection()
        output = Path(self.tmp.name) / "all-1275.zip"
        existing = Path(self.tmp.name) / "all-1275.part01.zip"
        existing.write_bytes(b"do-not-overwrite")
        with self.assertRaises(FileExistsError):
            collect(self.root, output, selection_file=selection, split_mib=1)
        self.assertEqual(existing.read_bytes(), b"do-not-overwrite")
        self.assertFalse((Path(self.tmp.name) / "all-1275.part02.zip").exists())

    def test_split_requires_selection_and_rejects_invalid_size(self):
        selection = self._make_selection()
        output = Path(self.tmp.name) / "all-1275.zip"
        with self.assertRaises(InventoryError):
            collect(self.root, output, split_mib=256)
        with self.assertRaises(InventoryError):
            collect(self.root, output, selection_file=selection,
                    include_bundles=True, split_mib=256)
        with self.assertRaises(InventoryError):
            collect(self.root, output, selection_file=selection, split_mib=0)
        with self.assertRaises(InventoryError):
            collect(self.root, output, selection_file=selection, split_mib=2049)

    def test_missing_manifest_is_not_labeled_1275(self):
        next((self.root / "MainPackage/ManifestFiles").glob("*.bytes")).unlink()
        with self.assertRaises(InventoryError):
            inventory(self.root)


if __name__ == "__main__":
    unittest.main()
