"""Standard-library smoke/regression tests; run with python -m unittest."""

from pathlib import Path
import tempfile
import unittest
import zipfile
import zlib

try:
    from tools.resources.lala_manifest_compare import compare, inspect_archive
except ModuleNotFoundError:
    from lala_manifest_compare import compare, inspect_archive


class ComparisonTests(unittest.TestCase):
    def test_changed_zip_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old = root / "old.zip"
            new = root / "new.zip"
            for path, version, content in ((old, 1262, b"old"), (new, 1275, b"new")):
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(f"DataPackage_{version}_test.bytes", content)
                    archive.writestr(f"DataPackage_{version}_test.hash", zlib.crc32(content).to_bytes(4, "little").hex().encode())
            result = compare(inspect_archive(old, "DataPackage"), inspect_archive(new, "DataPackage"))
            self.assertEqual((result["old_version"], result["new_version"]), ("1262", "1275"))
            self.assertTrue(result["manifest_changed"])
            self.assertTrue(result["hash_file_changed"])
            self.assertTrue(result["old_crc_verified"])
            self.assertTrue(result["new_crc_verified"])

    def test_reject_missing_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("MainPackage_1275_a.bytes", b"data")
            with self.assertRaises(ValueError):
                inspect_archive(archive_path, "MainPackage")


if __name__ == "__main__":
    unittest.main()
