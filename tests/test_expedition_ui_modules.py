"""Expedition UI module boundaries and backwards-compatible patch points."""
import unittest
from unittest.mock import patch

from wlre.ui import expedition_ui
from wlre.ui.expedition import controls, panel, settings, planner, task_list, team_view, task_detail


class ExpeditionUiModuleTests(unittest.TestCase):
    def test_legacy_panel_is_a_compatible_main_panel(self):
        self.assertTrue(issubclass(expedition_ui.ExpeditionPanel, panel.ExpeditionPanel))
        for name in ('render', 'update_detail', 'config', 'show_task', 'update_filter',
                     'settings_path', 'load_settings', 'save', 'preferences_changed',
                     'flush_preferences', 'destroyed', 'request_plans', 'collect_plans',
                     'start', 'update_inventory'):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(expedition_ui.ExpeditionPanel, name)))

    def test_existing_catalog_patch_point_is_preserved(self):
        catalog = {'tasks': {'1': {}}, 'levels': {'1': {}}}
        with patch('wlre.ui.expedition_ui.load_catalog', return_value=catalog):
            self.assertIs(expedition_ui.ExpeditionPanel._load_catalog(None), catalog)

    def test_existing_planner_patch_point_is_preserved(self):
        prediction = {'42': ([], {})}
        with patch('wlre.ui.expedition_ui.plan_quests', return_value=prediction):
            self.assertIs(expedition_ui.ExpeditionPanel._plan_quests(
                None, [], [], 80, {}), prediction)

    def test_view_builders_and_mixins_exist(self):
        for callback in (controls.build_controls, controls.bind_control_changes,
                         task_list.build_task_table, team_view.build_companion_table,
                         task_detail.build_task_detail):
            self.assertTrue(callable(callback))
        self.assertIs(expedition_ui.ExpeditionPanel.show_task,
                      task_detail.ExpeditionTaskDetailMixin.show_task)
        self.assertIs(expedition_ui.ExpeditionPanel.render_catalog_rows,
                      task_list.ExpeditionTaskListMixin.render_catalog_rows)
        self.assertIs(expedition_ui.ExpeditionPanel.render_companion_rows,
                      team_view.ExpeditionTeamListMixin.render_companion_rows)

    def test_server_side_protocol_is_not_imported_into_view_helpers(self):
        self.assertIs(expedition_ui.plan_quests, planner.plan_quests)
        self.assertTrue(callable(settings.ExpeditionSettingsMixin.flush_preferences))


if __name__ == '__main__':
    unittest.main()
