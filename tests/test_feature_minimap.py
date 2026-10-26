"""Minimap feature extraction contracts: geometry and safe click behavior."""
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from wlre.ui.home_map import HomeMap
from wlre.features.minimap.map_view import MinimapCanvasMixin
from wlre.features.minimap.buttons import MinimapPickMixin


class Projection:
    @staticmethod
    def pixel_to_packet(u, v):
        return u, v

    @staticmethod
    def packet_to_pixel(x, y):
        return x, y


class FakeMap(MinimapCanvasMixin, MinimapPickMixin):
    def __init__(self):
        self.canvas = SimpleNamespace(winfo_width=lambda: 1040,
                                      winfo_height=lambda: 1040)
        self.projection = Projection()
        self.portal_rows = []
        self.npc_rows = []
        self.selected_portal = None
        self.selected_npc = None
        self.selected_id = 10000
        self.update_portal_button = Mock()
        self.on_pick = Mock(return_value=True)
        self.on_move = Mock()
        self.go_portal = Mock()
        self.select_portal = Mock()
        self.note = Mock()


class MinimapFeatureTests(unittest.TestCase):
    def test_home_map_public_canvas_callbacks_are_inherited(self):
        for name in ('resize', 'view', 'screen_pixel', 'draw'):
            with self.subTest(name=name):
                self.assertIs(getattr(HomeMap, name),
                              getattr(MinimapCanvasMixin, name))
        for name in ('pick', 'double_pick'):
            with self.subTest(name=name):
                self.assertIs(getattr(HomeMap, name),
                              getattr(MinimapPickMixin, name))

    def test_projection_geometry_and_selection_safe(self):
        obj = FakeMap()
        self.assertEqual(obj.view(), (8.0, 8.0, 1.0))
        self.assertEqual(obj.screen_pixel(100, 150), (108.0, 158.0))
        self.assertTrue(obj.pick(SimpleNamespace(x=108, y=158)))
        obj.on_pick.assert_called_once_with(10000, 100, 150)
        obj.on_move.assert_not_called()
        self.assertFalse(obj.pick(SimpleNamespace(x=-10, y=100)))
        obj.on_move.assert_not_called()

    def test_only_double_click_can_trigger_manual_move(self):
        obj = FakeMap()
        result = obj.double_pick(SimpleNamespace(x=108, y=158))
        self.assertEqual(result, 'break')
        obj.on_move.assert_called_once_with()
        obj.on_pick.assert_called_once_with(10000, 100, 150)

    def test_no_projection_never_sends_move(self):
        obj = FakeMap()
        obj.projection = None
        self.assertFalse(obj.pick(SimpleNamespace(x=100, y=100)))
        self.assertEqual(obj.double_pick(SimpleNamespace(x=100, y=100)),
                         'break')
        obj.on_pick.assert_not_called()
        obj.on_move.assert_not_called()

    def test_portal_hit_selects_without_movement_command(self):
        obj = FakeMap()
        portal = {'room': 1}
        with patch('wlre.features.minimap.buttons.nearest_marker',
                   return_value=portal):
            self.assertFalse(obj.pick(SimpleNamespace(x=108, y=158)))
        obj.select_portal.assert_called_once_with(portal)
        obj.on_pick.assert_not_called()
        obj.on_move.assert_not_called()


    def test_npc_roster_is_not_drawn_even_if_selected(self):
        obj = FakeMap()
        obj.canvas = Mock()
        obj.canvas.winfo_width.return_value = 1040
        obj.canvas.winfo_height.return_value = 1040
        obj.state = {'player': {'scene': 10000}, 'location': {}}
        obj.image, obj.route, obj.photo = None, None, None
        obj._resize_job = None
        npc = {'name': 'NPC測試', 'x': 100, 'y': 150}
        obj.npc_rows = [npc]
        obj.selected_npc = npc
        with patch('wlre.features.minimap.map_view.current_position',
                   return_value=None):
            obj.draw()
        obj.canvas.delete.assert_called_once_with('all')
        # No purple NPC dot or selected-NPC text should be drawn.
        obj.canvas.create_oval.assert_not_called()
        obj.canvas.create_text.assert_not_called()

    def test_portals_and_player_marker_remain_on_canvas(self):
        obj = FakeMap()
        obj.canvas = Mock()
        obj.canvas.winfo_width.return_value = 1040
        obj.canvas.winfo_height.return_value = 1040
        obj.image, obj.route, obj.photo = None, None, None
        obj._resize_job = None
        obj.portal_rows = [{'kind': 'door', 'name': '返回出口',
                            'direct_eligible': True}]
        obj.npc_rows = [{'name': 'NPC測試', 'x': 100, 'y': 150}]
        obj.state = {'player': {'scene': 10000}, 'location': {}}
        with patch('wlre.features.minimap.map_view.portal_map_pixel',
                   return_value=(100, 150)), patch(
                'wlre.features.minimap.map_view.current_position',
                return_value={'scene': 10000, 'x': 100, 'y': 150,
                              'filled': True, 'kind': 'confirmed'}):
            obj.draw()
        ovals = [call.kwargs for call in obj.canvas.create_oval.call_args_list]
        self.assertEqual(len(ovals), 2)  # portal, player; never NPC
        self.assertEqual(ovals[0]['fill'], '#183e4d')
        self.assertEqual(ovals[1]['fill'], '#ed4747')
        obj.canvas.create_line.assert_called()  # portal spiral remains

    def test_invisible_npc_has_no_canvas_click_hotspot(self):
        obj = FakeMap()
        obj.npc_rows = [{'name': 'NPC測試', 'x': 100, 'y': 150}]
        obj.select_npc = Mock()
        self.assertTrue(obj.pick(SimpleNamespace(x=108, y=158)))
        obj.select_npc.assert_not_called()
        obj.on_pick.assert_called_once_with(10000, 100, 150)

        # For 1275 the normal navigation guard still prohibits movement.
        obj.maps = SimpleNamespace(supports_navigation=False)
        obj.on_pick.reset_mock()
        self.assertFalse(obj.pick(SimpleNamespace(x=108, y=158)))
        obj.select_npc.assert_not_called()
        obj.on_pick.assert_not_called()
        self.assertIn('未通過驗證', obj.note.set.call_args.args[0])

    def test_sidebar_npc_selection_remains_available(self):
        from wlre.features.npc.panel import NPCInteractionMixin
        page = NPCInteractionMixin()
        npc = {'scene': 10000, 'name': 'NPC測試', 'x': 100, 'y': 150}
        page.npc_rows = [npc]
        page.npc_list = Mock()
        page.npc_list.curselection.return_value = (0,)
        page.select_npc = Mock()
        page.on_pick = Mock()
        page.selected_id = 10000
        page.choose_npc()
        page.select_npc.assert_called_once_with(npc)
        page.on_pick.assert_called_once_with(10000, 100, 150)


if __name__ == '__main__':
    unittest.main()
