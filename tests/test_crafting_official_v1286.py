import unittest

from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.items.crafting_official_v1286 import RecipeCatalog, build_add_packet, decode_schedule, compare_legacy_recipes


class OfficialRecipeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = RecipeCatalog([
            {'recipe_id': 10, 'item_id': 31109, 'time_id': 0, 'limit_kind': 0},
            {'recipe_id': 11, 'item_id': 31109, 'time_id': 1078, 'read_only': True},
        ])

    def test_multiple_recipes_and_limited_read_only(self):
        self.assertEqual([r['recipe_id'] for r in self.catalog.for_item(31109)], [10, 11])
        with self.assertRaises(ProtocolError):
            build_add_packet(self.catalog, 11, 7, 1, [])

    def test_legacy_matching_does_not_guess_between_same_output_recipes(self):
        old = {31109: {'item_id': 31109}, 1: {'item_id': 1}}
        result = compare_legacy_recipes(old, self.catalog)
        self.assertEqual(result['ambiguous'], [{'item_id': 31109, 'recipe_ids': [10, 11]}])
        self.assertEqual(result['removed_legacy_item_ids'], [1])

    def test_add_packet_contains_recipe_and_item_in_official_order(self):
        packet = build_add_packet(self.catalog, 10, 7, 2, [{'index': 3, 'count': 4}])
        expected = Writer().u16(7).u16(10).u16(31109).u8(2).u8(1).u8(3).u8(4).u16(0).u8(0).build()
        self.assertEqual(packet, Packet(64, 1, expected))

    def test_schedule_uses_recipe_id_and_resolves_item(self):
        record = Writer().u8(1).u16(10).u32(1500).u8(2).u32(5).build()
        event = decode_schedule(Packet(64, 1, record + b'\x01'), self.catalog)
        self.assertEqual(event['rows'][0]['recipe_id'], 10)
        self.assertEqual(event['rows'][0]['item_id'], 31109)
        self.assertEqual(event['rows'][0]['elapsed'], 1.5)
        self.assertEqual(decode_schedule(Packet(64, 16, record), self.catalog)['type'], 'craft_added')
        with self.assertRaises(ProtocolError):
            decode_schedule(Packet(64, 1, record[:-1]), self.catalog)
        with self.assertRaises(ProtocolError):
            decode_schedule(Packet(64, 16, Writer().u8(1).u16(99).u32(0).u8(1).u32(1).build()), self.catalog)
