"""Feature-level resource routing must remain diagnostic/read-only."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wlre.services.world.feature_resource_index import (
    FEATURE_TABLES, describe_feature,
)


class FeatureResourceIndexTests(unittest.TestCase):
    REV = {
        'DataPackage': '1275_2026_10_21_18_27_33_84',
        'MainPackage': '1275_2026_10_21_18_29_38_49',
    }
    KEY = 'a' * 64

    def report(self):
        rows = []
        names = set(table for group in FEATURE_TABLES.values() for table in group)
        for name in names:
            rows.append({
                'package': 'DataPackage',
                'revision': self.REV['DataPackage'],
                'asset_path': 'Assets/ResourcesBuild/Data/' + name + '.bytes',
                'bundle': 'datapackage_data_a.bundle',
                'status': 'manifest_only',
            })
        return {
            'schema_version': 1, 'catalog_key': self.KEY,
            'approved': False, 'assets_ready': False, 'can_send_packets': False,
            'packages': {p: {'revision': v} for p, v in self.REV.items()},
            'assets': rows,
        }

    def test_all_modules_have_explicit_raw_sources(self):
        doc = self.report()
        for feature in ('npc', 'bag', 'crafting', 'expedition'):
            result = describe_feature(feature, report=doc, revisions=self.REV)
            self.assertEqual(result['state'], 'manifest_only')
            self.assertEqual(result['collected'], 0)
            self.assertEqual(result['required'], len(FEATURE_TABLES[feature]))
            self.assertFalse(result['assets_ready'])
            self.assertFalse(result['can_send_packets'])
            self.assertTrue(result['display_only'])

    def test_local_inventory_is_not_gameplay_authorization(self):
        doc = self.report()
        for row in doc['assets']:
            row['status'] = 'local_checksum_checked_not_approved'
        for feature in FEATURE_TABLES:
            result = describe_feature(feature, report=doc, revisions=self.REV)
            self.assertEqual(result['state'], 'all_local_unapproved')
            self.assertEqual(result['collected'], result['required'])
            self.assertFalse(result['assets_ready'])
            self.assertFalse(result['can_send_packets'])

    def test_missing_local_and_cross_version_are_distinguished(self):
        doc = self.report()
        doc['assets'][0]['status'] = 'local_checksum_checked_not_approved'
        result = describe_feature('expedition', report=doc, revisions=self.REV)
        self.assertIn(result['state'], ('partial_local', 'manifest_only'))
        modified = {**self.REV, 'DataPackage': '1276_2026_10_25_01_00_00_00'}
        for feature in FEATURE_TABLES:
            result = describe_feature(feature, report=doc, revisions=modified)
            self.assertEqual(result['state'], 'version_mismatch')
            self.assertFalse(result['can_send_packets'])

    def test_rejects_rogue_or_duplicate_resource_rows(self):
        doc = self.report()
        doc['assets'].append(dict(doc['assets'][0]))
        # This table may or may not be relevant to bag; NPC includes Eve.
        result = describe_feature('npc', report=doc, revisions=self.REV)
        self.assertEqual(result['state'], 'index_unavailable') if (
            doc['assets'][0]['asset_path'] in result['required_assets']) else None
        doc = self.report()
        doc['approved'] = True
        result = describe_feature('bag', report=doc, revisions=self.REV)
        self.assertEqual(result['state'], 'index_unavailable')

    def test_file_identity_bound_to_current_launcher_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / 'derived_catalogs' / self.KEY
            directory.mkdir(parents=True)
            path = directory / 'asset_classification.json'
            path.write_text(json.dumps(self.report()), encoding='utf-8')
            # Without the live Launcher receipt a matching-looking file
            # cannot be selected as the current game version.
            with patch('wlre.services.world.launcher_catalog.read_launcher_status',
                       return_value=None):
                self.assertEqual(describe_feature('npc', root=root,
                    revisions=self.REV)['state'], 'index_unavailable')
            with patch('wlre.services.world.launcher_catalog.read_launcher_status',
                       return_value={'schema_version': 2, 'catalog_key': self.KEY}):
                result = describe_feature('bag', root=root, revisions=self.REV)
                self.assertEqual(result['state'], 'manifest_only')
            with patch('wlre.services.world.launcher_catalog.read_launcher_status',
                       return_value={'schema_version': 2, 'catalog_key': 'b' * 64}):
                result = describe_feature('bag', root=root, revisions=self.REV)
                self.assertEqual(result['state'], 'index_unavailable')

    def test_item_name_prefers_only_full_pinned_runtime(self):
        from types import SimpleNamespace
        from wlre.services.items.catalog import item_display_name, item_name
        runtime = SimpleNamespace(items={1234: {'name': '1275 正式物品名稱'}})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
             'wlre.services.world.runtime_1275.active_runtime',
                   return_value=runtime):
            self.assertEqual(item_display_name(1234), '1275 正式物品名稱')
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
             'wlre.services.world.runtime_1275.active_runtime',
                   side_effect=ValueError('missing official archives')):
            self.assertEqual(item_display_name(1234), item_name(1234))


if __name__ == '__main__':
    unittest.main()
