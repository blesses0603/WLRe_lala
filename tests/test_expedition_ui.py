import os
import tempfile
import tkinter as tk
import unittest
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.ui.expedition_ui import ExpeditionPanel


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'Requires a desktop')
class ExpeditionPanelTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.local_data = patch.dict(os.environ, {'LOCALAPPDATA': self.folder.name})
        self.local_data.start()
        self.root = tk.Tk()
        self.app = SimpleNamespace(root=self.root, live_active=True, _settings_key=None,
            snapshot={}, send=Mock(return_value=True), settings_identity=lambda: 'a'*64)
        self.catalog = {'levels': {'1': {'reduction': 0, 'difficulty': 2}}, 'tasks': {
            '1': {'id': 1, 'minutes': 360, 'faith_cost': 20, 'difficulty': 1, 'area': 1, 'condition': [0, 0, 0]},
            '2': {'id': 2, 'minutes': 240, 'faith_cost': 10, 'difficulty': 1, 'area': 2, 'condition': [0, 0, 0]}}}
        with patch('wlre.ui.expedition_ui.load_catalog', return_value=self.catalog):
            self.panel = ExpeditionPanel(self.root, self.app)
        self.panel.pack(fill='both', expand=True)
        self.state = {'expedition': {'ready': True, 'outpost_ready': True,
            'level': 1, 'quests': {'1': 1, '2': 2}, 'revision': 1, 'roles': {}, 'teams': {}, 'status': '待機'}}
        self.app.snapshot = self.state

    def tearDown(self):
        self.root.destroy()
        self.local_data.stop()
        self.folder.cleanup()

    def test_threshold_controls_filter_tasks_and_enqueue_configuration(self):
        self.panel.hours.set('5')
        self.panel.render(self.state)
        self.assertEqual(len(self.panel.tasks.get_children()), 1)
        self.panel.hours.set('3')
        self.assertEqual(len(self.panel.tasks.get_children()), 2)
        self.panel.faith.set('85')
        self.panel.start_button.invoke()
        self.assertEqual(self.app.send.call_args.args[0], {'type': 'start_expedition',
            'settings': {'min_hours': 3.0, 'faith_min': 85, 'item_id': 0, 'quests': [], 'auto_claim': True, 'min_success': 75}})
        self.app.send.return_value = False
        self.panel.start()
        self.assertIn('重新登入', self.panel.status.get())

    def test_expedition_window_uses_play_and_pause_without_changing_commands(self):
        start_button = self.panel.start_button
        stop_button = self.panel.stop_button
        for button, expected_text in (
            (start_button, '啟動自動派遣'),
            (stop_button, '停止'),
        ):
            image = button.tk.splitlist(button.cget('image'))[0]
            self.assertTrue(image)
            self.assertEqual(self.root.tk.call('image', 'width', image), 28)
            self.assertEqual(button.cget('text'), expected_text)
            self.assertEqual(str(button.cget('compound')), 'none')
        self.assertNotEqual(start_button.tk.splitlist(start_button.cget('image'))[0],
                            stop_button.tk.splitlist(stop_button.cget('image'))[0])
        self.panel.render(self.state)
        start_button.invoke()
        self.assertEqual(self.app.send.call_args.args[0]['type'],
                         'start_expedition')
        self.app.send.reset_mock()
        stop_button.invoke()
        self.app.send.assert_called_once_with({'type': 'stop_expedition'})

    def test_missing_catalog_disables_start_and_displays_requirement(self):
        self.panel.catalog = {'tasks': {}, 'levels': {}}
        self.panel.render(self.state)
        self.assertTrue(self.panel.start_button.instate(['disabled']))
        self.assertIn('內建遠征資料不完整', self.panel.note.get())

    def test_auto_downloaded_preview_never_enables_dispatch(self):
        self.panel.catalog = {
            'source_kind': 'automatic_1275_unapproved_preview',
            'tasks': self.catalog['tasks'], 'levels': self.catalog['levels'],
            'npcs': {}, 'display_only': True, 'can_send_packets': False,
        }
        self.panel.render(self.state)
        self.assertTrue(self.panel.start_button.instate(['disabled']))
        self.assertIn('唯讀', self.panel.note.get())
        self.panel.start()  # Even direct API calls cannot bypass disabled UI.
        self.app.send.assert_not_called()
        self.assertIn('不可自動派遣', self.panel.status.get())

    def test_account_preferences_reload_without_automatic_start(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'LOCALAPPDATA': folder}):
            self.panel.hours.set('7.5')
            self.panel.faith.set('90')
            self.panel.auto_claim.set(False)
            self.panel.save()
            self.panel.load_settings('b'*64)
            self.panel.load_settings('a'*64)
            self.assertEqual(self.panel.hours.get(), '7.5')
            self.assertEqual(self.panel.faith.get(), '90')
            self.assertFalse(self.panel.auto_claim.get())
            self.app.send.assert_not_called()
            self.panel.load_settings('b'*64)
            self.assertEqual(self.panel.faith.get(), '80')

    def test_backpack_options_update_automatically_and_exclude_locked_items(self):
        self.state['inventory'] = {'ready': True, 'reliable': True, 'items': {
            '1': {'item_id': 34014, 'count': 3}, '2': {'item_id': 34068, 'count': 5, 'locked': True}}}
        self.panel.render(self.state)
        self.assertEqual(set(self.panel.items.values()), {0, 34014})
        self.assertTrue(any('可用 3' in text for text in self.panel.items))
        self.state['inventory']['items']['1']['count'] = 1
        self.panel.render(self.state)
        self.assertTrue(any('可用 1' in text for text in self.panel.items))
        self.app.send.assert_not_called()
        self.assertIn('已自動檢查', self.panel.status.get())

    def test_defaults_and_account_switch_autosave_use_original_account(self):
        self.assertEqual(self.panel.hours.get(), '0')
        self.assertEqual(self.panel.min_success.get(), '75')
        self.app._settings_key = 'a'*64
        self.panel.load_settings('a'*64)
        self.panel.hours.set('2')
        self.panel.min_success.set('85')
        self.app._settings_key = 'b'*64
        self.panel.load_settings('b'*64)  # flush A's pending edits under A's identity
        self.assertEqual(self.panel.hours.get(), '0')
        self.assertEqual(self.panel.min_success.get(), '75')
        self.panel.min_success.set('90')
        self.panel.flush_preferences()
        self.app._settings_key = 'a'*64
        self.panel.load_settings('a'*64)
        self.assertEqual(self.panel.hours.get(), '2.0')
        self.assertEqual(self.panel.min_success.get(), '85.0')
        self.app.send.assert_not_called()

    def test_success_column_and_background_planner(self):
        self.catalog['tasks']['1']['success_rate'] = 500
        self.state['expedition']['roles'] = {str(i): {'index': i, 'npc_id': i, 'faith': 90,
            'state': 0, 'stats': {'level': 1, 'degree': 0}} for i in range(1, 12)}
        self.panel.render(self.state)
        self.assertIsNotNone(self.panel.plan_future)
        deadline = time.monotonic() + 3
        while self.panel.plan_future is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.005)
        self.assertIsNone(self.panel.plan_future)
        self.assertEqual(self.panel.tasks.item('1', 'values')[2], '50%')
        self.panel.tasks.selection_set('1'); self.panel.show_task()
        self.assertIn('未達最低成功率 75%', self.panel.task_detail.get())

    def test_task_rows_show_name_reduced_time_and_rewards(self):
        quest = self.catalog['tasks']['1']
        quest.update(name='測試採集任務', expedition_exp=25, exp=100,
            rewards=[{'kind': 6, 'id': 13, 'value': 20}, {'kind': 10, 'id': 34014, 'value': 2}],
            special_reward={'kind': 6, 'id': 4, 'value': 3}, special_rate=300)
        self.catalog['levels']['1']['reduction'] = 30
        self.panel.render(self.state)
        row = self.panel.tasks.item('1', 'values')
        self.assertEqual(row[0], '測試採集任務')
        self.assertEqual(row[1], '5 小時 49 分鐘')
        self.assertEqual(len(row), 3)
        self.panel.tasks.selection_set('1')
        self.panel.show_task()
        detail = self.panel.task_detail.get()
        self.assertIn('遠征經驗 × 25', detail)
        self.assertIn('遠征幣 × 20', detail)
        self.assertIn('桃太郎飯糰 × 2', detail)
        self.assertIn('機率獎勵：紫鑽 × 3', detail)
        self.panel.tasks.selection_set('1')
        self.panel.show_task()
        self.assertIn('消耗好友度：20', self.panel.task_detail.get())
        self.state['expedition']['revision'] += 1
        self.panel.render(self.state)
        self.assertEqual(self.panel.tasks.selection(), ('1',))

    def test_unavailable_name_is_not_replaced_with_made_up_title(self):
        self.panel.render(self.state)
        self.assertEqual(self.panel.tasks.item('1', 'values')[0], '任務名稱待補齊')

    def test_failed_flush_preserves_original_account_and_pending_preferences(self):
        self.panel.load_settings('a'*64)
        self.panel.hours.set('6')
        pending=self.panel.pending_preferences
        with patch('wlre.ui.expedition_ui.expedition_settings.save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.panel.load_settings('b'*64)
        self.assertEqual(self.panel.key,'a'*64)
        self.assertEqual(self.panel.pending_preferences,pending)
        self.assertEqual(self.panel.hours.get(),'6')
        self.assertTrue(self.panel.flush_preferences())

    def test_corrupt_target_settings_do_not_switch_or_overwrite(self):
        from wlre.storage.expedition_settings import settings_file
        self.panel.load_settings('a'*64)
        target=settings_file('b'*64);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text('{broken')
        with self.assertRaises(ValueError):self.panel.load_settings('b'*64)
        self.assertEqual(self.panel.key,'a'*64)
        self.assertEqual(target.read_text(),'{broken')
