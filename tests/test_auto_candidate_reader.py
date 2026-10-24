"""Only allow unapproved automatic item candidates for text display."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from wlre.services.world.auto_candidate_reader import (
    candidate_item_name, _load)


class ReadOnlyAutomaticItemNameTests(unittest.TestCase):
    KEY = 'a' * 64

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.dir = self.root / 'derived_catalogs' / self.KEY
        self.dir.mkdir(parents=True)
        self.path = self.dir / 'verified_raw_inventory.zip'
        self._receipt()
        _load.cache_clear()
        self.addCleanup(_load.cache_clear)

    def _receipt(self, key=None):
        doc = {
            'schema_version': 2, 'status': 'review_required',
            'checked_at_utc': '2026-10-24T12:00:00+00:00',
            'catalog_key': self.KEY if key is None else key,
            'data_compatibility': 'unverified',
            'protocol_compatibility': 'unverified',
            'assets_ready': False, 'can_send_packets': False,
        }
        (self.root / 'launcher_catalog_status.json').write_text(
            json.dumps(doc), encoding='utf-8')

    def _inventory(self, *, hash_mismatch=False, approved=False,
                   name='1275 自動接收物品'):
        member = 'candidate_indexes/item_data.json'
        document = {
            'revision': 1275, 'source': 'ItemData_C',
            'record_count': 1,
            'records': {'123': {'name': name, 'price': 20}},
        }
        raw = json.dumps(document).encode()
        digest = hashlib.sha256(raw).hexdigest()
        row = {
            'size': len(raw),
            'sha256': '0'*64 if hash_mismatch else digest,
            'source': 'derived_unapproved',
        }
        meta = {
            'schema_version': 1, 'catalog_key': self.KEY,
            'formal_approved': approved, 'assets_ready': False,
            'can_send_packets': False,
            'protocol_compatibility': 'unverified',
            'entries': {member: row},
        }
        with ZipFile(self.path, 'w') as z:
            z.writestr('inventory.json', json.dumps(meta))
            z.writestr(member, raw)

    def test_automatic_candidate_names_are_read_only(self):
        self._inventory()
        self.assertEqual(candidate_item_name(123, root=self.root),
                         '1275 自動接收物品')
        self.assertIsNone(candidate_item_name(999, root=self.root))
        self.assertIsNone(candidate_item_name(True, root=self.root))
        self.assertIsNone(candidate_item_name(65536, root=self.root))

    def test_expansion_to_automatically_received_expedition_preview(self):
        from wlre.services.world.auto_candidate_reader import candidate_expedition_catalog
        member = 'candidate_indexes/expedition_quests.json'
        doc = {
            'schema_version': 1, 'revision': 1275,
            'sources': {'AdventureData_C': 'b'*64, 'AdventureLvData_C': 'c'*64},
            'approved': False, 'assets_ready': False,
            'can_send_packets': False,
            'records': {
                'tasks': {'1': {
                    'id': 1, 'area': 1, 'name_id': 222,
                    'minutes': 300, 'difficulty': 1, 'faith_cost': 20,
                    'condition': [0, 0, 0]}},
                'levels': {'1': {'teams': 1, 'difficulty': 1, 'reduction': 0}},
            }
        }
        data = json.dumps(doc).encode()
        meta = {
            'schema_version': 1, 'catalog_key': self.KEY,
            'formal_approved': False, 'assets_ready': False,
            'can_send_packets': False, 'protocol_compatibility': 'unverified',
            'entries': {member: {
                'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'source': 'derived_unapproved',
            }}
        }
        with ZipFile(self.path, 'w') as zip_file:
            zip_file.writestr('inventory.json', json.dumps(meta))
            zip_file.writestr(member, data)
        result = candidate_expedition_catalog(root=self.root)
        self.assertIsNotNone(result)
        self.assertEqual(result['tasks']['1']['name_id'], 222)
        self.assertTrue(result['display_only'])
        self.assertFalse(result['can_send_packets'])
        self.assertEqual(result['source_kind'],
                         'automatic_1275_unapproved_preview')
        self._receipt('b'*64)
        self.assertIsNone(candidate_expedition_catalog(root=self.root))

    def test_wrong_identity_or_tampered_archive_rejected(self):
        self._inventory()
        self._receipt('b'*64)
        self.assertIsNone(candidate_item_name(123, root=self.root))
        self._receipt()
        self._inventory(hash_mismatch=True)
        self.assertIsNone(candidate_item_name(123, root=self.root))
        self._inventory(approved=True)
        _load.cache_clear()
        self.assertIsNone(candidate_item_name(123, root=self.root))

    def test_invalid_name_must_not_enter_ui(self):
        self._inventory(name='bad\x00name')
        self.assertIsNone(candidate_item_name(123, root=self.root))

    def test_missing_formal_1275_uses_auto_name_only_as_display_fallback(self):
        from wlre.services.items.catalog import item_display_name
        self._inventory()
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), \
             patch('wlre.services.world.runtime_1275.active_runtime',
                   side_effect=ValueError('full ZIP missing')), \
             patch('wlre.services.world.auto_candidate_reader.data_root',
                   return_value=self.root.parent), \
             patch('wlre.services.world.auto_candidate_reader.candidate_item_name',
                   return_value='1275 自動接收物品') as preview:
            self.assertEqual(item_display_name(123), '1275 自動接收物品')
            preview.assert_called_once_with(123)


if __name__ == '__main__':
    unittest.main()
