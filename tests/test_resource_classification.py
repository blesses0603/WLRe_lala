"""Offline regression for 1275/next-version path-only resource categorization."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from wlre.services.world.resource_classification import (
    _read_existing_inventory, build_classification,
    classify_asset_path, ResourceClassificationError,
)


class ResourceClassificationTests(unittest.TestCase):
    KEY = 'a' * 64

    def indexes(self):
        return {
            'DataPackage': {
                'header': {'file_version': '2.2.5', 'package_name': 'DataPackage',
                           'package_version': '1275_2026_10_21_18_27_33_84'},
                'bundles': [{'name': 'datapackage_data_e.bundle'}],
                'assets': [
                    {'path': 'Assets/ResourcesBuild/Data/Eve.bytes',
                     'bundle_name': 'datapackage_data_e.bundle'},
                    {'path': 'Assets/ResourcesBuild/Data/DailyTaskData_C.bytes',
                     'bundle_name': 'datapackage_data_e.bundle'},
                ],
            },
            'MainPackage': {
                'header': {'file_version': '2.2.5', 'package_name': 'MainPackage',
                           'package_version': '1275_2026_10_21_18_29_38_49'},
                'bundles': [{'name': 'mainpackage_house.bundle'}],
                'assets': [
                    {'path': 'Assets/ResourcesBuild/Model/House/Tent/a.prefab',
                     'bundle_name': 'mainpackage_house.bundle'},
                    {'path': 'Assets/ResourcesBuild/Particle/prefab.prefab',
                     'bundle_name': 'mainpackage_house.bundle'},
                ],
            },
        }

    def test_filename_only_and_directory_classification(self):
        self.assertEqual(classify_asset_path(
            'DataPackage', 'Assets/ResourcesBuild/Data/Eve.bytes'),
            ('npc', 'filename_rule'))
        self.assertEqual(classify_asset_path(
            'DataPackage', 'Assets/ResourcesBuild/Data/DailyTaskData_C.bytes')[0],
            'quests')
        self.assertEqual(classify_asset_path(
            'DataPackage', 'Assets/ResourcesBuild/Data/AdventureData_C.bytes')[0],
            'expedition')
        self.assertEqual(classify_asset_path(
            'MainPackage', 'Assets/ResourcesBuild/Model/House/Tent/a.prefab')[0],
            'housing')
        self.assertEqual(classify_asset_path(
            'MainPackage', 'Assets/ResourcesBuild/Particle/prefab.prefab')[0],
            'effects')
        self.assertEqual(classify_asset_path(
            'DataPackage', 'Assets/ResourcesBuild/Data/UnknownData_C.bytes')[1],
            'unclassified_filename')

    def test_path_traversal_and_unapproved_formats_rejected(self):
        for path in (
            '../Assets/ResourcesBuild/Data/Eve.bytes',
            'Assets/ResourcesBuild/Data/../Eve.bytes',
            'Assets/ResourcesBuild/Data\\Eve.bytes',
        ):
            with self.assertRaises(ResourceClassificationError):
                classify_asset_path('DataPackage', path)
        with self.assertRaises(ResourceClassificationError):
            classify_asset_path('MainPackage', 'Assets/ResourcesBuild/Data/Eve.bytes\x00')

    def test_include_all_assets_without_pretending_downloaded(self):
        doc = build_classification(self.indexes(), self.KEY)
        self.assertEqual(len(doc['assets']), 4)
        self.assertTrue(all(x['status'] == 'manifest_only' for x in doc['assets']))
        self.assertEqual(sum(x['count'] for x in doc['summary']), 4)
        self.assertFalse(doc['approved'])
        self.assertFalse(doc['assets_ready'])
        self.assertFalse(doc['can_send_packets'])

    def test_local_cache_reuse_is_checksum_only_not_formal_approval(self):
        member = 'tables/datapackage_data_e.bundle/Eve.bytes'
        body = b'audited fixture'
        row = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'verified_raw_inventory.zip'
            meta = {'schema_version': 1, 'catalog_key': self.KEY,
                    'entries': {member: row}}
            with ZipFile(path, 'w') as z:
                z.writestr('inventory.json', json.dumps(meta))
                z.writestr(member, body)
            raw, indexes = _read_existing_inventory(path, self.KEY)
            self.assertEqual(indexes, [])
            doc = build_classification(self.indexes(), self.KEY,
                                       local_raw=raw)
            found = next(x for x in doc['assets'] if x['asset_path'].endswith('Eve.bytes'))
            self.assertEqual(found['status'], 'local_checksum_checked_not_approved')
            self.assertEqual(found['local_sha256'], row['sha256'])
            self.assertFalse(doc['assets_ready'])
            # Never apply a cached copy from a different official catalog.
            self.assertEqual(_read_existing_inventory(path, 'b'*64), ({}, []))
            meta['entries'][member]['sha256'] = '0' * 64
            with ZipFile(path, 'w') as z:
                z.writestr('inventory.json', json.dumps(meta))
                z.writestr(member, body)
            self.assertEqual(_read_existing_inventory(path, self.KEY), ({}, []))

    def test_duplicated_or_unknown_bundle_rejected(self):
        fixture = self.indexes()
        fixture['DataPackage']['assets'].append(
            fixture['DataPackage']['assets'][0])
        with self.assertRaises(ResourceClassificationError):
            build_classification(fixture, self.KEY)
        fixture = self.indexes()
        fixture['DataPackage']['assets'][0]['bundle_name'] = 'missing.bundle'
        with self.assertRaises(ResourceClassificationError):
            build_classification(fixture, self.KEY)


if __name__ == '__main__':
    unittest.main()
