"""No display required: current entry never loads historical geometry."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from wlre.ui.official_navigation_preview import preview_defaults, mapping_summary


class OfficialNavigationEntryTests(unittest.TestCase):
    def test_selected_map_does_not_inherit_other_scene_coordinates(self):
        state={'player':{'scene':10001,'x':12,'y':34}}
        self.assertEqual(preview_defaults(state,12050),(12050,'',''))
        self.assertEqual(preview_defaults(state),(10001,12,34))
        self.assertEqual(preview_defaults(state,10001),(10001,12,34))

    def test_same_version_mapping_only(self):
        runtime=SimpleNamespace(stages={10011:{'model_id':10001}},
            catalog_identity=SimpleNamespace(key='current'),
            smallmaps=SimpleNamespace(catalog_key='current',models={10001}))
        self.assertIn('SmallMap2D_10001（同版圖片已入庫）',mapping_summary(10011,runtime))
        runtime.smallmaps.catalog_key='old'
        self.assertIn('版本不符',mapping_summary(10011,runtime))
        self.assertIn('不猜測',mapping_summary(99999,runtime))
        self.assertIn('未使用歷史種子',mapping_summary(10011,None))

    def test_house_mapping_remains_entry_exit_only(self):
        runtime=SimpleNamespace(stages={10001:{'model_id':10000}})
        self.assertIn('僅支援進入與離開',mapping_summary(63501,runtime))
        self.assertIn('僅支援進入與離開',mapping_summary(10001,runtime))

    def test_entry_does_not_read_even_present_or_corrupt_seed(self):
        from wlre.ui.gui import App
        app=SimpleNamespace(root=object(),snapshot={},home_map=SimpleNamespace(selected_id=12050),
                            navigation_windows=[])
        with (patch('wlre.ui.navigation_gui.NavigationWindow',side_effect=AssertionError('legacy accessed')),
              patch('wlre.ui.official_navigation_preview.OfficialNavigationPreview') as preview):
            viewer=App.open_navigation(app)
        self.assertEqual(app.navigation_windows,[viewer])
        self.assertEqual(preview.call_args.kwargs['suggested_scene'],12050)
        self.assertNotIn('on_legacy',preview.call_args.kwargs)
        self.assertFalse(hasattr(App,'open_legacy_navigation'))

    def test_official_projection_never_reads_legacy_coordinates(self):
        from wlre.services.world.smallmaps import SmallMaps
        maps=SmallMaps.__new__(SmallMaps)
        maps._official=True;maps.source_revision='1296';maps.coordinates=None
        stage=dict(map_width=6000,map_height=6000,small_offset_x=12,small_offset_y=12)
        maps._stage_1275=Mock(return_value=(stage,'M10001'))
        with patch('wlre.services.world.smallmaps.Coordinates',side_effect=AssertionError('legacy read')):
            projection,model=maps.projection(10001)
        self.assertEqual(model,'M10001')
        self.assertFalse(maps.supports_navigation)
        self.assertIsNone(maps.coordinates)
        self.assertEqual(projection.origin,(0,0,0))
        point=(123,456)
        self.assertEqual(tuple(round(v) for v in projection.pixel_to_packet(*projection.packet_to_pixel(*point))),point)

    def test_official_home_map_never_loads_legacy_mesh(self):
        from wlre.features.minimap.navigation_ui import MinimapNavigationMixin
        page=MinimapNavigationMixin()
        page.maps=SimpleNamespace(source_revision='1296',supports_navigation=True,
            projection=Mock(return_value=(object(),'M10001')),image=Mock(return_value=object()))
        page.repository=Mock();page.note=Mock();page.map_title=Mock()
        page.refresh_portals=Mock();page.draw=Mock();page.scene_display_name=Mock(return_value='場景10001')
        page.show_map(10001)
        page.repository.load.assert_not_called()
        self.assertIsNone(page.mesh)
        self.assertIn('官方路徑請開啟導航預覽',page.note.set.call_args.args[0])


if __name__=='__main__':unittest.main()
