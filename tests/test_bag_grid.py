"""Inventory grid model checks; no Tk display or game network required."""
import unittest

from wlre.ui.bag_grid import PAGE_SIZE, visible_items, item_details


class BagGridModelTests(unittest.TestCase):
    @staticmethod
    def inventory():
        return {
            'ready': True, 'reliable': True, 'capacity': 145,
            'reserved': {'8': 2},
            'items': {
                '8': {'index': 8, 'item_id': 34144, 'count': 6},
                '2': {'index': 2, 'item_id': 34026, 'count': 5},
                '12': {'index': 12, 'item_id': 34144, 'count': 1},
            },
        }

    def test_grid_is_five_by_five(self):
        self.assertEqual(PAGE_SIZE, 25)

    def test_slots_are_sorted_by_real_index(self):
        self.assertEqual([index for index, *_ in visible_items(self.inventory())], ['2', '8', '12'])

    def test_filter_matches_name_and_id(self):
        inv = self.inventory()
        self.assertEqual([index for index, *_ in visible_items(inv, '34144')], ['8', '12'])
        self.assertEqual([index for index, *_ in visible_items(inv, '夢守')], ['2'])
        self.assertEqual(visible_items(inv, '找不到這個'), [])

    def test_card_shows_actual_item_count_and_availability(self):
        inv = self.inventory()
        details = item_details(inv, '8', inv['items']['8'])
        self.assertEqual(details['id'], 34144)
        self.assertEqual(details['index'], 8)
        self.assertEqual(details['count'], 6)
        self.assertEqual(details['reserved'], 2)
        self.assertEqual(details['available'], 4)
        self.assertEqual(details['name'], '5倍經驗聖水')

    def test_card_never_guesses_heal_properties(self):
        inv = self.inventory()
        details = item_details(inv, '2', inv['items']['2'])
        self.assertFalse(details['effects'].get('hp'))
        self.assertFalse(details['effects'].get('sp'))

    def test_empty_inventory(self):
        self.assertEqual(visible_items({'items': {}}, ''), [])


if __name__ == '__main__':
    unittest.main()
