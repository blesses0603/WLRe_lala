"""P4 feature window ownership regression tests (no network required)."""
import unittest
from unittest.mock import Mock, patch

from wlre.ui.gui import App
from wlre.ui.feature_navigation import FeatureWindowController


class FeatureWindowOwnership(unittest.TestCase):
    def test_app_public_windows_use_controller(self):
        for name in ('open_feature', 'hide_feature', 'hide_all_features',
                     'open_instances', 'hide_instances', 'open_resources',
                     'open_attributes'):
            with self.subTest(name=name):
                self.assertIs(getattr(App, name),
                              getattr(FeatureWindowController, name))

    def test_open_instance_only_renders_its_confirmed_snapshot(self):
        app = FeatureWindowController()
        window = Mock()
        window.winfo_exists.return_value = True
        app.assert_ui_thread = Mock()
        app.feature_windows = {'instance': window}
        app.root = Mock()
        app.snapshot = {'instances': {'main': {}, 'coop': {}}}
        app.live_active = False
        app.instance_panel = Mock()
        with patch('wlre.ui.feature_navigation.center_on_main') as center:
            app.open_instances()
        center.assert_called_once()
        app.instance_panel.render.assert_called_once_with(
            app.snapshot, live=False)
        window.deiconify.assert_called_once()
        window.lift.assert_called_once()
        window.focus_set.assert_called_once()
        app.assert_ui_thread.assert_called_once_with()

    def test_hiding_windows_does_not_destroy_or_reconnect(self):
        app = FeatureWindowController()
        app.assert_ui_thread = Mock()
        a, b = Mock(), Mock()
        a.winfo_exists.return_value = True
        b.winfo_exists.return_value = True
        app.feature_windows = {'party': a, 'instance': b}
        app.hide_all_features()
        a.withdraw.assert_called_once()
        b.withdraw.assert_called_once()
        a.destroy.assert_not_called()
        b.destroy.assert_not_called()

    def test_nonexistent_window_not_brought_forward(self):
        app = FeatureWindowController()
        window = Mock()
        window.winfo_exists.return_value = False
        app.assert_ui_thread = Mock()
        app.feature_windows = {'party': window}
        with patch('wlre.ui.feature_navigation.center_on_main') as center:
            app.open_feature('party')
        center.assert_not_called()
        window.deiconify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
