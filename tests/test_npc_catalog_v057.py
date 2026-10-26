"""NPC phase-1: distinguish location references and actual EventData indices."""
from _tk_native_pump import create_root
import sys
import gzip
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock

from wlre.services.world.npc_catalog import NPCIndex, scene_npcs, npc_detail
from wlre.paths import RESOURCE_ROOT


def verified_index_file(path, scenes):
    path.write_text(json.dumps({
        'version': 1262, 'source': 'EventData.NewNpc', 'scenes': scenes
    }), encoding='utf-8')


class NPCCatalogTests(unittest.TestCase):
    def test_bundled_official_eve_index(self):
        index = NPCIndex()
        self.assertTrue(index.path.is_file())
        self.assertEqual(index.path.name, 'npc_event_index_1262.json.gz')
        self.assertEqual(len(index.scenes), 1256)
        self.assertEqual(sum(map(len, index.scenes.values())), 10879)
        rows=[v for group in index.scenes.values() for v in group]
        self.assertEqual(sum(row['event_count'] > 0 for row in rows), 8014)
        self.assertEqual(sum(row['event_count'] == 0 for row in rows), 2865)
        self.assertEqual(sum(row.get('buy_kind', 0) != 0 for row in rows), 32)

    def test_gzip_catalog_decodes_without_loss(self):
        source = RESOURCE_ROOT/'npc_event_index_1262.json.gz'
        with gzip.open(source, 'rt', encoding='utf-8') as stream:
            data=json.load(stream)
        self.assertEqual(data['version'], 1262)
        self.assertEqual(data['source'], 'EventData.NewNpc')
        self.assertEqual(data['bundle_md5'], '81af690395d5e6a233afa9a664e2c555')

    def test_position_only_marker_never_fabricates_event_index(self):
        rows = scene_npcs(100, [{
            'kind': 0, 'name': '行商', 'index': 99,
            'id': 321, 'x': 24, 'y': 25
        }])
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['verified'])
        self.assertIsNone(rows[0]['npc_index'])
        self.assertEqual(rows[0]['source'], 'map_position_reference')
        self.assertIn('不會送出對話封包', npc_detail(rows[0]))

    def test_verified_event_index_uses_exact_id_and_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'event_npcs.json'
            verified_index_file(path, {'100': [{
                'index': 5, 'npc_id': 321, 'x': 24, 'y': 25,
                'event_count': 2, 'name': '行商'
            }]})
            catalog = NPCIndex(path)
            rows = scene_npcs(100, [{'kind': 0, 'name': '行商',
                                     'npc_id': 321, 'x': 24, 'y': 25}], catalog)
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]['verified'])
            self.assertEqual(rows[0]['npc_index'], 5)
            self.assertEqual(rows[0]['source'], 'EventData.NewNpc')
            self.assertIn('已核對', npc_detail(rows[0]))
            wrong = scene_npcs(101, [{'kind': 0, 'name': '行商',
                                      'npc_id': 321, 'x': 24, 'y': 25}], catalog)
            self.assertFalse(wrong[0]['verified'])
            no_id = scene_npcs(100, [{'kind': 0, 'name': '行商',
                                      'x': 24, 'y': 25}], catalog)
            self.assertFalse(no_id[0]['verified'])

    def test_only_independently_verified_npcs_are_added(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'npcs.json'
            verified_index_file(path, {'100': [{
                'index': 2, 'npc_id': 987, 'x': 3, 'y': 4,
                'event_count': 1
            }]})
            rows = scene_npcs(100, [], NPCIndex(path))
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]['npc_id'], rows[0]['npc_index']),
                             (987, 2))

    def test_official_zero_event_npc_is_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'npcs.json'
            verified_index_file(path, {'12903': [{
                'index': 7, 'npc_id': 18001, 'x': 600, 'y': 700,
                'event_count': 0, 'event_ids': [], 'name': 'Npc',
                'base_define': 4, 'buy_kind': 0
            }]})
            rows=scene_npcs(12903, [], NPCIndex(path))
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]['verified'])
            self.assertEqual(rows[0]['event_count'], 0)
            self.assertNotEqual(rows[0]['name'], 'Npc')
            self.assertIn('無互動事件', npc_detail(rows[0]))

    def test_bad_source_duplicate_index_and_invalid_types_fail_closed(self):
        valid = {'index': 2, 'npc_id': 123, 'x': 4, 'y': 5,
                 'event_count': 1}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'npcs.json'
            for payload in (
                {'version': 1262, 'source': 'MapActionNpcData', 'scenes': {}},
                {'version': 1262, 'source': 'EventData.NewNpc', 'scenes': {
                    '100': [valid, valid]}},
                {'version': 1262, 'source': 'EventData.NewNpc', 'scenes': {
                    '100': [{**valid, 'index': True}]}},
                {'version': 1262, 'source': 'EventData.NewNpc', 'scenes': {
                    '100': [{**valid, 'event_count': 2, 'event_ids': [1]}]}},
            ):
                path.write_text(json.dumps(payload), encoding='utf-8')
                with self.subTest(source=payload['source']), self.assertRaises(ValueError):
                    NPCIndex(path)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin',
                     'Requires a desktop')
class NPCSceneUITests(unittest.TestCase):
    def setUp(self):
        from wlre.ui.home_map import HomeMap
        self.root = create_root()
        self.root.geometry('600x500')
        self.pick = Mock()
        self.portal = Mock()
        self.move = Mock()
        self.map = HomeMap(self.root, self.pick, Mock(),
                           on_move=self.move, on_portal=self.portal, compact=True)
        self.map.pack(fill='both', expand=True)
        # Isolate the single-marker fixture from the now-bundled NPC roster.
        self.map.npc_index=None
        self.map.portals.data['entities']['12903'] = [{
            'kind': 0, 'name': '行商', 'x': 120, 'y': 80,
            'index': 123, 'npc_id': 900
        }]
        self.map.show_map(12903)
        self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    def test_npc_and_portal_lists_are_separate(self):
        self.assertEqual(len(self.map.npc_rows), 1)
        self.assertIn('行商', self.map.npc_list.get(0))
        self.assertFalse(any('行商' in self.map.portal_list.get(i)
                             for i in range(self.map.portal_list.size())))
        self.assertIsNone(self.map.npc_rows[0]['npc_index'])
        self.map.npc_list.selection_set(0)
        self.map.choose_npc()
        self.pick.assert_called_once_with(12903, 120, 80)
        self.portal.assert_not_called()
        self.move.assert_not_called()
        self.assertIn('不會送出對話封包', self.map.npc_message.get())


if __name__ == '__main__':
    unittest.main()


# These historical tests verify bundled 1262 fixtures explicitly. Production
# LaLa now defaults to 1275, with no implicit source fallback.
from unittest.mock import patch as _legacy_patch
_legacy_context = None


def setUpModule():
    global _legacy_context
    _legacy_context = _legacy_patch(
        'wlre.services.world.runtime_1275.baseline_revision', return_value='1262')
    _legacy_context.start()
    from wlre.services.world.npc_item_data import item_catalog
    item_catalog.cache_clear()


def tearDownModule():
    from wlre.services.world.npc_item_data import item_catalog
    item_catalog.cache_clear()
    _legacy_context.stop()

