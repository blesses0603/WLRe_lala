"""P1b shared catalog UI keeps the existing normal/cooperative callbacks."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from wlre.ui.instance_catalog_ui import InstanceCatalogMixin, build_instance_catalog
from wlre.ui.instance_ui import InstanceModePage
from wlre.features.dungeon.panel import DungeonModePage
from wlre.features.cooperative.panel import CooperativeModePage


class CatalogExtractionContract(unittest.TestCase):
    def test_both_feature_pages_keep_original_catalog_api(self):
        for name in ('on_catalog_selected', '_selected_catalog',
                     '_update_create_button'):
            with self.subTest(method=name):
                self.assertIs(getattr(InstanceModePage, name),
                              getattr(InstanceCatalogMixin, name))
        self.assertTrue(issubclass(DungeonModePage, InstanceModePage))
        self.assertTrue(issubclass(CooperativeModePage, InstanceModePage))

    def test_selection_rejects_invalid_or_missing_index(self):
        class Selection(InstanceCatalogMixin):
            catalog_records = ({'kind': 1, 'name': '副本'},)
            catalog_table = Mock()
        page = Selection()
        page.catalog_table.selection.return_value = ()
        self.assertIsNone(page._selected_catalog())
        for value in ('catalog_nope', 'catalog_15'):
            page.catalog_table.selection.return_value = (value,)
            self.assertIsNone(page._selected_catalog())
        page.catalog_table.selection.return_value = ('catalog_0',)
        self.assertIs(page._selected_catalog(), page.catalog_records[0])

    def test_create_button_respects_catalog_and_server_guard(self):
        class Selection(InstanceCatalogMixin):
            catalog_records = ({'kind': 1, 'name': '副本'},)
            catalog_table = Mock()
            create_button = Mock()
            creation_hint = Mock()
            _creation_block_reasons = ('伺服器未同步',)
        page = Selection()
        page.catalog_table.selection.return_value = ('catalog_0',)
        page._creation_ready = False
        page._update_create_button()
        page.create_button.state.assert_called_with(['disabled'])
        self.assertIn('伺服器未同步',
                      page.creation_hint.set.call_args.args[0])
        page._creation_ready = True
        page._update_create_button()
        page.create_button.state.assert_called_with(['!disabled'])


if __name__ == '__main__':
    unittest.main()
