"""Manifest-based instance bundle collection does not alter installed assets."""
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from tools.resources.collect_instance_bundles import BUNDLES, collect


class Collector(unittest.TestCase):
    def test_collect_1262_bundles_without_changing_originals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'yoo'
            expected = {}
            for name, (digest, size, _) in BUNDLES.items():
                source = root / 'DataPackage' / 'BundleFiles' / digest[:2] / digest / '__data'
                source.parent.mkdir(parents=True, exist_ok=True)
                content = b'UnityFS' + b'\x00' * (size - 7)
                source.write_bytes(content)
                expected[name] = (source, content)
            output = collect(root, Path(temp) / 'instances.zip')
            with ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()),
                                 set(expected) | {'manifest_inventory.json'})
                inventory = json.loads(archive.read('manifest_inventory.json'))
                self.assertEqual(len(inventory['files']), 4)
                for name, (source, content) in expected.items():
                    self.assertEqual(archive.read(name), content)
                    self.assertEqual(source.read_bytes(), content)

    def test_rejects_missing_and_wrong_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'yoo'
            (root / 'DataPackage' / 'BundleFiles').mkdir(parents=True)
            with self.assertRaises(FileNotFoundError):
                collect(root, Path(temp) / 'out.zip')
            name, (digest, size, _) = next(iter(BUNDLES.items()))
            p = root / 'DataPackage' / 'BundleFiles' / digest[:2] / digest / '__data'
            p.parent.mkdir(parents=True)
            p.write_bytes(b'invalid')
            with self.assertRaises(ValueError):
                collect(root, Path(temp) / 'out.zip')
            self.assertFalse((Path(temp) / 'out.zip').exists())
