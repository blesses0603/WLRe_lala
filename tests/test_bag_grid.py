"""Inventory grid model checks; no Tk display or game network required."""
import unittest

from wlre.ui.bag_grid import (PAGE_SIZE, COLUMNS, ROWS, ICON_SIZE, STORAGE_ROWS,
                              STORAGE_ICON_SIZE, grid_profile, page_count,
                              visible_items, item_details, responsive_profile, reflow_page)


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

    def test_larger_icons_and_non_five_by_five_grid(self):
        self.assertEqual(COLUMNS, 6)
        self.assertEqual(ROWS, 4)
        self.assertEqual(PAGE_SIZE, 24)
        self.assertEqual(ICON_SIZE, 64)

    def test_hyperspace_storage_48_entries_fit_without_clipping(self):
        self.assertEqual(grid_profile(compact=True), (6, 2, 60))
        self.assertEqual(STORAGE_ROWS, 2)
        self.assertEqual(STORAGE_ICON_SIZE, 60)
        self.assertEqual(page_count(48, compact=True), 4)
        self.assertEqual(page_count(50, compact=True), 5)
        self.assertEqual(page_count(0, compact=True), 1)
        self.assertEqual(page_count(48), 2)
        self.assertEqual(grid_profile(), (6, 4, 64))

    def test_responsive_grid_keeps_icon_sizes_and_avoids_cropped_columns(self):
        self.assertEqual(responsive_profile(980, 470), (6, 4, 64))
        self.assertEqual(responsive_profile(515, 280), (5, 3, 64))
        self.assertEqual(responsive_profile(195, 190), (2, 2, 64))
        self.assertEqual(responsive_profile(950, 180, compact=True), (6, 2, 60))
        self.assertEqual(responsive_profile(380, 96, compact=True), (4, 1, 60))
        self.assertEqual(page_count(48, compact=True, columns=4, rows=1), 12)

    def test_reflow_keeps_selected_or_first_visible_item(self):
        self.assertEqual(reflow_page(2, 24, 10, 145, selected_position=57), 5)
        self.assertEqual(reflow_page(2, 24, 10, 145), 4)
        self.assertEqual(reflow_page(9, 24, 6, 14), 2)
        self.assertEqual(reflow_page(0, 24, 12, 0), 0)

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


# Historical 1262 fixtures require an explicit test-only baseline.
from unittest.mock import patch as _legacy_baseline_patch
_legacy_baseline_context = None

def setUpModule():
    global _legacy_baseline_context
    _legacy_baseline_context = _legacy_baseline_patch(
        'wlre.services.world.runtime_1275.baseline_revision', return_value='1262')
    _legacy_baseline_context.start()

def tearDownModule():
    _legacy_baseline_context.stop()
