"""P2 minimap route/scene lifecycle regression without game network."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.ui.home_map import HomeMap
from wlre.features.minimap.navigation_ui import MinimapNavigationMixin


class MapLifecycleTests(unittest.TestCase):
    def test_old_public_navigation_methods_retained(self):
        for name in ('show_map', 'set_state', 'set_route'):
            with self.subTest(method=name):
                self.assertIs(getattr(HomeMap, name),
                              getattr(MinimapNavigationMixin, name))

    def test_route_requires_verified_scene_mesh(self):
        page = MinimapNavigationMixin()
        page.mesh = SimpleNamespace(scene_id=10000)
        page.image = object()
        page.selected_id = 10000
        page.state = {'navigation': {'scene': 10000, 'stale': False}}
        page.draw = Mock()
        page.route = None
        mismatch = {'scene_resource': 20000, 'points': [(3, 0, 5)]}
        page.set_route(mismatch)
        self.assertIsNone(page.route)
        page.draw.assert_not_called()
        accepted = {'scene_resource': 10000, 'points': [(3, 0, 5)]}
        page.set_route(accepted)
        self.assertIs(page.route, accepted)
        page.draw.assert_called_once_with()
        page.draw.reset_mock()
        page.state['navigation']['stale'] = True
        page.set_route(accepted)
        self.assertIs(page.route, accepted)
        page.draw.assert_not_called()
        page.set_route(None)
        self.assertIsNone(page.route)
        page.draw.assert_called_once_with()

    def test_scene_without_verified_map_disables_projection(self):
        page = MinimapNavigationMixin()
        page.route = object()
        page.image = object()
        page.mesh = object()
        page.projection = object()
        page.maps = SimpleNamespace(projection=Mock(return_value=(object(), 3)),
                                    image=Mock(return_value=None))
        page.map_title = Mock()
        page.note = Mock()
        page.repository = Mock()
        page.refresh_portals = Mock()
        page.draw = Mock()
        with patch('wlre.features.minimap.navigation_ui.parse_map_id',
                   return_value=10000), patch(
                'wlre.features.minimap.navigation_ui.map_label',
                return_value='測試場景'):
            page.show_map(10000)
        self.assertEqual(page.selected_id, 10000)
        self.assertIsNone(page.projection)
        self.assertIsNone(page.mesh)
        page.repository.load.assert_not_called()
        page.refresh_portals.assert_called_once_with()
        page.draw.assert_called_once_with()

    def test_stale_navigation_clears_existing_route(self):
        page = MinimapNavigationMixin()
        page.state = {'navigation': {'scene': 10000, 'revision': 1}}
        page.selected_id = 10000
        page.image = object()
        page._signature = None
        page.route = object()
        page.draw = Mock()
        page.update_portal_button = Mock()
        page.update_npc_buttons = Mock()
        page.show_dialogue_status = Mock()
        page.portal_status = Mock()
        page.note = Mock()
        page.set_state({
            'player': {'scene': 10000},
            'navigation': {'scene': 10000, 'revision': 2, 'stale': True},
            'location': {}
        })
        self.assertIsNone(page.route)
        self.assertIn('障礙資料已變更', page.note.set.call_args.args[0])
        page.draw.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
