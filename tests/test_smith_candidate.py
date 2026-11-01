import struct
import unittest
from unittest.mock import patch

from wlre.services.world.smith_candidate import parse_smith_candidate, mark_timed_recipes


class SmithCandidateTests(unittest.TestCase):
    def test_read_only_recipe_cannot_be_added_to_crafting(self):
        from wlre.network.wire import ProtocolError
        from wlre.services.items.crafting import RECIPES, recipe_plan
        from wlre.services.items.crafting_plan import validate_rows
        with patch.dict(RECIPES, {'123': {'read_only': True}}):
            with self.assertRaises(ProtocolError):
                recipe_plan(None, 123, 1)
            with self.assertRaises(ProtocolError):
                validate_rows([{'item_id': 123, 'count': 1}])

    def test_timed_recipes_are_read_only(self):
        record = bytearray(33)
        struct.pack_into('<H', record, 0, 123)
        timed = bytearray(record)
        struct.pack_into('<H', timed, 28, 1078)
        data = struct.pack('<iH', 2, 10) + record + struct.pack('<H', 11) + timed
        rows = mark_timed_recipes(parse_smith_candidate(data))
        self.assertEqual([row['candidate_row_key'] for row in rows], [10, 11])
        self.assertEqual([row['recipe_id'] for row in rows], [10, 11])
        self.assertEqual([row['read_only'] for row in rows], [False, True])

    def test_preserves_multiple_recipes_for_same_output(self):
        record = bytearray(33)
        struct.pack_into('<H', record, 0, 123)
        first = struct.pack('<H', 10) + record
        second = struct.pack('<H', 11) + record
        rows = parse_smith_candidate(struct.pack('<i', 2) + first + second)
        self.assertEqual([row['item_id'] for row in rows], [123, 123])
        self.assertEqual([row['candidate_row_key'] for row in rows], [10, 11])
        self.assertEqual([row['order'] for row in rows], [1, 2])

    def test_rejects_duplicate_keys_and_truncated_data(self):
        record = bytearray(33)
        struct.pack_into('<H', record, 0, 123)
        row = struct.pack('<H', 10) + record
        for data in (struct.pack('<i', 2) + row + row,
                     struct.pack('<i', 1) + row[:-1]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_smith_candidate(data)

    def test_candidate_inventory_requires_known_outputs_and_materials(self):
        from wlre.services.world.resource_rebuilder import _derive_candidate_indexes
        record = bytearray(33)
        struct.pack_into('<H', record, 0, 123)
        struct.pack_into('<HB', record, 8, 456, 1)
        raw = struct.pack('<iH', 1, 10) + record
        sources = {'tables/a/SmithData_C.bytes': raw,
                   'tables/a/ItemData_C.bytes': b'fixture'}
        with patch('wlre.services.world.itemdata_v1.parse_itemdata', return_value={123: {}, 456: {}}):
            self.assertIn('candidate_indexes/smith_recipes_35.json',
                          _derive_candidate_indexes(sources, revision='1286'))
            self.assertIn('candidate_indexes/smith_recipes_35.json',
                          _derive_candidate_indexes(sources, revision='1287'))
        with patch('wlre.services.world.itemdata_v1.parse_itemdata', return_value={123: {}}):
            self.assertEqual(_derive_candidate_indexes(sources, revision='1286'), {})
