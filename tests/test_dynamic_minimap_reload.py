"""Minimap must rebind current runtime before loading the first live scene."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from wlre.features.minimap.navigation_ui import MinimapNavigationMixin
from wlre.features.minimap.map_view import MinimapCanvasMixin
from wlre.services.world.smallmaps import SmallMaps
from wlre.services.world.runtime_1275 import Runtime1275Unavailable
from wlre.ui.home_map import HomeMap


def runtime(key='a',width=7520):
    # Synthetic runtime and artwork; no official image seed.
    from smallmap_runtime_fixtures import attach
    return attach(SimpleNamespace(revision=1286,catalog_identity=SimpleNamespace(key=key*64),
        stages={12170:{'model_id':12170,'map_width':width,'map_height':6433,
                       'small_offset_x':12,'small_offset_y':84}},
        npc_index=SimpleNamespace(scenes={}),interact_index=SimpleNamespace(scenes={}),talks={}))


class Page(MinimapNavigationMixin):
    refresh_runtime_sources=HomeMap.refresh_runtime_sources


class DynamicMinimapReloadTests(unittest.TestCase):
    def setUp(self):
        self.current=runtime()
        self.live=patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=self.current)
        self.active=patch('wlre.services.world.runtime_1275.active_runtime',return_value=self.current)
        self.attempted=patch('wlre.services.world.dynamic_bundle_runtime.dynamic_attempted',return_value=True)
        self.portals=patch('wlre.ui.home_map.Portals',return_value=SimpleNamespace(data={
            'source_revision':1286,'source_ready':True,'scene_names':{12170:'測試場景'}}))
        for item in (self.live,self.active,self.attempted,self.portals):
            result=item.start()
            self.addCleanup(item.stop)
            if item is self.live:self.live_mock=result
            if item is self.active:self.active_mock=result
        self.page=Page()
        self.page.maps=SmallMaps(source_revision='1275')
        self.page.portals=SimpleNamespace(data={'source_revision':1275,'scene_names':{}})
        self.page.state={}
        self.page.selected_id=None
        self.page._signature=None
        self.page.image=self.page.mesh=self.page.projection=self.page.route=None
        for name in ('map_title','note','repository','refresh_portals','draw','portal_status',
                     'update_portal_button','update_npc_buttons','show_dialogue_status'):
            setattr(self.page,name,Mock())

    def test_first_scene_12170_rebinds_before_projection_and_loads_database_artwork(self):
        # This was rejected by the old 1275-bound SmallMaps before rebind.
        self.assertFalse(self.page.maps.has_image(12170))
        self.page.show_map(12170)
        self.assertEqual(self.page.maps.source_revision,'1286')
        self.assertIsNotNone(self.page.projection)
        self.assertEqual(self.page.image.size,(1024,1024))
        self.assertIsNone(self.page.map_error)
        self.assertIsNone(self.page.mesh)
        self.assertFalse(self.page.maps.supports_navigation)
        self.page.repository.load.assert_not_called()
        self.page.refresh_portals.assert_called_once_with()

    def test_same_identity_image_republish_after_portal_refresh_reloads(self):
        from smallmap_runtime_fixtures import Images
        self.page.set_state({'player':{'scene':12170}})
        old=self.page.image
        self.current.smallmaps=Images(self.current.catalog_identity.key,(12170,))
        self.page.refresh_runtime_sources()
        self.assertIsNone(self.page.image)
        self.page.set_state({'player':{'scene':12170}})
        self.assertIsNotNone(self.page.image)
        self.assertIsNot(self.page.image,old)
        self.current.smallmaps=None
        self.page.refresh_runtime_sources()
        self.page.set_state({'player':{'scene':12170}})
        self.assertIsNone(self.page.image)
        self.assertIsNone(self.page.projection)

    def test_runtime_rebind_closes_stale_npc_windows_and_selections(self):
        windows=[]
        for name in ('npc_shop_window','npc_choice_window','npc_history_window'):
            window=Mock()
            window.winfo_exists.return_value=True
            setattr(self.page,name,window)
            windows.append(window)
        self.page.selected_npc={'npc_id':1}
        self.page.selected_portal={'id':1}
        self.page.show_map(12170)
        self.assertIsNone(self.page.selected_npc)
        self.assertIsNone(self.page.selected_portal)
        for window in windows:
            window.destroy.assert_called_once_with()
        for name in ('npc_shop_window','npc_choice_window','npc_history_window'):
            self.assertIsNone(getattr(self.page,name))

    def test_same_scene_reloads_after_timestamp_only_runtime_change(self):
        self.page.set_state({'player':{'scene':12170}})
        old_image=self.page.image
        old_rate=self.page.projection.rate
        replacement=runtime('b',width=8000)
        self.live_mock.return_value=replacement
        self.active_mock.return_value=replacement
        self.page.set_state({'player':{'scene':12170}})
        self.assertEqual(self.page.selected_id,12170)
        self.assertIsNotNone(self.page.image)
        self.assertIsNot(self.page.image,old_image)
        self.assertNotEqual(self.page.projection.rate,old_rate)
        self.assertEqual(self.page._map_runtime_catalog_key,'b'*64)

    def test_same_scene_does_not_redecode_unchanged_runtime(self):
        with patch.object(self.page,'show_map',wraps=self.page.show_map) as load:
            self.page.set_state({'player':{'scene':12170}})
            image=self.page.image
            self.page.set_state({'player':{'scene':12170}})
            self.assertEqual(load.call_count,1)
            self.assertIs(self.page.image,image)

    def test_rebind_from_portal_refresh_does_not_prevent_same_scene_reload(self):
        self.page.set_state({'player':{'scene':12170}})
        replacement=runtime('b',width=8000)
        self.live_mock.return_value=replacement
        self.active_mock.return_value=replacement
        self.assertTrue(self.page.refresh_runtime_sources())
        self.assertIsNone(self.page.image)
        self.page.set_state({'player':{'scene':12170}})
        self.assertIsNotNone(self.page.image)
        self.assertEqual(self.page._map_runtime_catalog_key,'b'*64)

    def test_invalidated_runtime_clears_old_image_without_historical_scene_fallback(self):
        self.page.set_state({'player':{'scene':12170}})
        self.assertIsNotNone(self.page.image)
        self.live_mock.return_value=None
        self.active_mock.side_effect=Runtime1275Unavailable('目前 Runtime 尚未驗證')
        self.page.set_state({'player':{'scene':12170}})
        self.assertIsNone(self.page.image)
        self.assertIsNone(self.page.projection)
        self.assertIn('Runtime 尚未驗證',self.page.map_error)

    def test_missing_current_scene_does_not_use_legacy_geometry_or_invent_absent_artwork(self):
        self.current.stages={}
        self.page.show_map(12170)
        self.assertIsNone(self.page.image)
        self.assertIsNone(self.page.projection)
        self.assertIn('模型對應',self.page.map_error)
        self.assertNotIn('沒有原始小地圖',self.page.map_error)

    def test_canvas_reports_actual_loader_reason_instead_of_missing_original(self):
        page=SimpleNamespace(_resize_job=None,canvas=Mock(),projection=None,
                             selected_id=12170,map_error='目前 Runtime 尚未驗證')
        page.canvas.winfo_width.return_value=300
        page.canvas.winfo_height.return_value=240
        MinimapCanvasMixin.draw(page)
        text=page.canvas.create_text.call_args.kwargs['text']
        self.assertIn('目前 Runtime 尚未驗證',text)
        self.assertNotIn('沒有原始小地圖',text)
        self.assertGreater(page.canvas.create_text.call_args.kwargs['width'],0)
