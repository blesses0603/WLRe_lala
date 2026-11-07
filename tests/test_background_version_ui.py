"""Observer hints revoke entry but cannot grant it or mutate a live Runtime."""
from dataclasses import replace
import inspect
import queue
import threading
import unittest
from unittest.mock import Mock, patch

from test_integrated_startup import StartupHarness, verified_result
from test_background_version_observer import Clock, identity
from wlre.services.background_version_observer import (
    ObservationResult, ObservationSchedule, version_identifiers_from_database,
)
from wlre.ui.background_version_controller import BackgroundVersionController
from wlre.ui.gui import App
from wlre.ui.login_controller import LoginController
from wlre.ui.session_event_coordinator import SessionEventCoordinator


class BackgroundVersionUiTests(unittest.TestCase):
    def setUp(self):
        self.app = StartupHarness()
        self.app.stop = Mock()
        self.app.dialog_parent = Mock(return_value=None)
        self.app._session_resource_hold = threading.Event()
        self.clock = Clock()
        self.app._background_schedule = ObservationSchedule(clock=self.clock, initial_delay=True)
        self.anchor = version_identifiers_from_database(identity())
        self.full = verified_result() | {'runtime_identity': identity()}
        with patch('wlre.ui.background_version_controller.time.monotonic', self.clock):
            self.app._background_full_check_finished(self.full, True)
        self.app.version_gate_state = 'ready'
        self.app._version_gate_result = self.full
        self.app._version_gate_entry_approved = True
        self.app._version_gate_checked = 100.0

    def result(self, *, status='identifiers_match', official=None, database=None):
        return ObservationResult(status, 'observed', official or self.anchor,
                                 database or self.anchor, '2026-11-07T11:10:00+00:00')

    def deliver(self, result):
        token = self.app._background_schedule.begin(force=True)
        self.assertIsNotNone(token)
        self.app._background_messages.put((token, result, self.clock()))
        with patch('wlre.ui.background_version_controller.time.monotonic', self.clock):
            self.app.poll_background_versions()

    def begin_worker(self):
        with patch('wlre.ui.background_version_controller.threading.Thread') as thread:
            self.assertTrue(self.app._start_background_observation(force=True))
        self.assertTrue(thread.call_args.kwargs['daemon'])
        self.assertEqual(thread.call_args.kwargs['name'], 'background-version-observer')
        return thread.call_args.kwargs['target']

    def test_matching_observation_never_refreshes_or_reauthorizes_full_gate(self):
        self.deliver(self.result())
        self.assertEqual(self.app._observer_state, 'match')
        self.assertEqual(self.app._version_gate_checked, 100.0)
        self.assertIs(self.app._version_gate_result, self.full)
        self.assertEqual(self.app._observer_anchor, self.anchor)
        self.assertTrue(self.app._version_gate_entry_approved)
        self.app.show_version_check.assert_not_called()
        self.assertIn('僅識別，非內容驗證', self.app._background_status.get())
        self.assertIn('5 分鐘', self.app._background_status.get())
        self.assertIn('非推播', self.app._background_status.get())
        self.assertIn('19:10:00 UTC+8', self.app._background_status.get())
        with patch('wlre.ui.background_version_controller.time.monotonic', return_value=301.0), \
             patch('wlre.ui.version_gate_controller.messagebox'), \
             patch.object(self.app, 'start_version_check') as check, \
             patch.object(self.app, '_start_background_observation') as light:
            self.assertFalse(self.app.can_login_after_version_check())
            check.assert_not_called()
            light.assert_called_once_with(force=True)
            self.assertTrue(self.app._version_gate_entry_approved)

    def test_fresh_full_gate_still_authorizes_only_through_existing_contract(self):
        self.deliver(self.result())
        with patch('wlre.ui.background_version_controller.time.monotonic', return_value=299.0):
            self.assertTrue(self.app.can_login_after_version_check())
        self.app._version_gate_entry_approved = False
        self.deliver(self.result())
        self.assertFalse(self.app._version_gate_entry_approved)
        with patch('wlre.ui.version_gate_controller.messagebox'):
            self.assertFalse(self.app.can_login_after_version_check())

    def test_changed_database_and_official_together_are_not_running_runtime_match(self):
        newer = replace(self.anchor, data_ver='1.3.23.0')
        self.app.live_active = True
        self.deliver(self.result(official=newer, database=newer))
        self.assertEqual(self.app._observer_state, 'changed')
        self.assertTrue(self.app._session_resource_hold.is_set())
        self.assertTrue(self.app._observer_requires_full_check)
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertIsNone(self.app._version_gate_result)
        self.assertEqual(self.app._version_gate_checked, 100.0)
        self.assertEqual(self.app._observer_anchor, self.anchor)
        self.app.show_version_check.assert_called_once_with()
        self.app.stop.assert_not_called()
        self.assertTrue(self.app.live_active)

    def test_failed_mismatched_malformed_and_anchorless_observations_block(self):
        for result, state, anchor in (
            (self.result(status='unverified'), 'unknown', self.anchor),
            (self.result(status='identifiers_differ', database=replace(self.anchor, exe_version='1.4.0')), 'different', self.anchor),
            ({'status': 'identifiers_match'}, 'unknown', self.anchor),
            (self.result(), 'no_anchor', None),
        ):
            with self.subTest(state=state):
                self.app._observer_anchor = anchor
                self.deliver(result)
                self.assertEqual(self.app._observer_state, state)
                self.assertTrue(self.app._observer_requires_full_check)
                self.assertIsNone(self.app._version_gate_result)
                self.assertFalse(self.app._version_gate_entry_approved)
                self.assertFalse(self.app._session_resource_hold.is_set())
                self.assertEqual(self.app._version_gate_checked, 100.0)
                with patch('wlre.ui.version_gate_controller.messagebox'), \
                     patch('wlre.ui.gui.run_client') as network:
                    self.app.assert_ui_thread = Mock()
                    App.connect(self.app)
                    network.assert_not_called()

    def test_matching_recovery_does_not_clear_hold_or_restore_old_approval(self):
        self.app.live_active = True
        self.deliver(self.result(status='unverified'))
        self.deliver(self.result())
        self.assertEqual(self.app._observer_state, 'match')
        self.assertTrue(self.app._observer_alarm)
        self.assertTrue(self.app._observer_requires_full_check)
        self.assertTrue(self.app._session_resource_hold.is_set())
        self.assertIsNone(self.app._version_gate_result)
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertIn('先前異常仍須完整檢查', self.app._background_status.get())
        self.assertEqual(self.app.show_version_check.call_count, 2)
        with patch('wlre.ui.version_gate_controller.messagebox'):
            self.app.continue_to_login()
        self.app.show_login.assert_not_called()

    def test_failed_observation_keeps_last_success_distinct_from_latest_unknown(self):
        self.deliver(self.result())
        successful = self.app._observer_last_success
        self.deliver(replace(self.result(status='unverified'), checked_at_utc='2026-11-07T11:20:00+00:00'))
        self.assertEqual(self.app._observer_last_success, successful)
        self.assertEqual(self.app._observer_state, 'unknown')
        self.assertIn('19:10:00 UTC+8', self.app._background_status.get())
        self.assertIn('未知', self.app._background_status.get())
        self.assertIn('退避', self.app._background_status.get())

    def test_live_full_verification_is_blocked_before_preparation_or_thread(self):
        self.app.live_active = True
        with patch('wlre.ui.version_gate_controller.messagebox') as dialogs, \
             patch('wlre.ui.version_gate_controller.threading.Thread') as thread, \
             patch('wlre.ui.version_gate_controller.prepare_on_launch') as prep, \
             patch('wlre.ui.version_gate_controller.run_prelogin_check') as check:
            self.app.start_version_check()
        dialogs.showinfo.assert_not_called()
        thread.assert_not_called()
        prep.assert_not_called()
        check.assert_not_called()
        self.assertIn('先安全中斷', self.app.version_gate_text.get())
        self.app.show_version_check.assert_called_once_with()
        self.assertEqual(self.app._observer_anchor, self.anchor)

    def test_worker_only_enqueues_and_has_no_app_or_tk_closure(self):
        worker = self.begin_worker()
        self.assertEqual(set(worker.__code__.co_freevars), {'messages', 'token'})
        with patch('wlre.ui.background_version_controller.observe_background_versions', return_value=self.result(status='unverified')):
            worker()
        self.assertFalse(self.app._observer_alarm)
        self.app.show_version_check.assert_not_called()
        self.app.poll_background_versions()
        self.assertTrue(self.app._observer_alarm)
        self.app.root.after.assert_not_called()

    def test_close_invalidates_pending_result_without_waiting_on_readonly_worker(self):
        worker = self.begin_worker()
        self.app.close_background_observer()
        with patch('wlre.ui.background_version_controller.observe_background_versions', return_value=self.result(status='unverified')):
            worker()
        self.app.poll_background_versions()
        self.assertFalse(self.app._observer_alarm)
        self.assertFalse(self.app._start_background_observation(force=True))
        self.assertFalse(self.app._background_busy)
        self.app.show_version_check.assert_not_called()
        self.app.root.after.assert_not_called()

    def test_full_generation_discards_late_observer_and_retains_single_flight(self):
        worker = self.begin_worker()
        self.app._background_full_check_started()
        self.app._background_full_check_finished(self.full, True)
        self.assertFalse(self.app._start_background_observation(force=True))
        with patch('wlre.ui.background_version_controller.observe_background_versions', return_value=self.result(status='unverified')):
            worker()
        self.app.poll_background_versions()
        self.assertFalse(self.app._observer_alarm)
        self.assertEqual(self.app._observer_anchor, self.anchor)
        self.assertIsNone(self.app._background_schedule.latest)
        self.assertEqual(self.app._background_schedule.seconds_until_due(), 300)
        self.assertFalse(self.app._background_busy)

    def test_completed_full_check_is_only_recovery_and_does_not_clear_old_event(self):
        self.app.live_active = True
        self.deliver(self.result(status='unverified'))
        self.app.live_active = False
        self.app._background_full_check_started()
        self.assertTrue(self.app._observer_requires_full_check)
        self.app._background_full_check_finished({'status': 'unverified'}, False)
        self.assertTrue(self.app._observer_requires_full_check)
        self.app._background_full_check_finished(self.full, True)
        self.assertFalse(self.app._observer_requires_full_check)
        self.assertFalse(self.app._observer_alarm)
        self.assertTrue(self.app._session_resource_hold.is_set())
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertEqual(self.app._observer_anchor, self.anchor)

    def test_default_delayed_poll_cadence_bounded_settings_and_no_extra_timers(self):
        self.app.poll_background_versions()
        self.assertFalse(self.app._background_busy)
        for entered, expected in (('0',60), ('99999',3600), ('nan',300), ('120',120)):
            self.app._observer_interval.set(entered)
            self.app.apply_observer_interval()
            self.assertEqual(self.app._background_schedule.interval_seconds, expected)
        self.clock.advance(119)
        with patch('wlre.ui.background_version_controller.threading.Thread') as thread:
            for _ in range(1000):
                self.app.poll_background_versions()
            thread.assert_not_called()
            self.clock.advance(1)
            self.app.poll_background_versions()
            self.app.poll_background_versions()
            self.app.recheck_background_versions()
            thread.assert_called_once()
        self.app.root.after.assert_not_called()

    def test_worker_error_and_thread_start_failure_are_fail_closed_sanitized(self):
        worker = self.begin_worker()
        with patch('wlre.ui.background_version_controller.observe_background_versions', side_effect=RuntimeError('private/path')):
            worker()
        self.app.poll_background_versions()
        self.assertTrue(self.app._observer_alarm)
        self.assertNotIn('private', self.app._background_status.get())
        with patch('wlre.ui.background_version_controller.threading.Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('private thread')
            self.app.recheck_background_versions()
        self.app.poll_background_versions()
        self.assertEqual(self.app._observer_state, 'unknown')
        self.assertFalse(self.app._background_busy)

    def test_alarm_cannot_be_dismissed_by_login_or_world_ready_transition(self):
        self.deliver(self.result(status='unverified'))
        self.app.show_version_check.reset_mock()
        LoginController.show_login(self.app)
        self.app.show_version_check.assert_called_once_with()
        self.app.show_version_check.reset_mock()
        self.app.login_window = None
        LoginController.show_main(self.app)
        self.app.show_version_check.assert_called_once_with()
        self.assertTrue(self.app._observer_alarm)

    def test_disconnect_under_hold_stays_in_gate_and_never_starts_full_check(self):
        self.deliver(self.result(status='unverified'))
        self.app.show_version_check.reset_mock()
        self.app.events = queue.Queue()
        self.app.events.put(('session_finished', None))
        self.app.live_active = True
        self.app.hide_all_features = Mock()
        self.app.update_role_choices = Mock()
        self.app._pending_display = None
        self.app.background_window = Mock(return_value=True)
        self.app.status = Mock()
        with patch.object(self.app, 'start_version_check') as check:
            SessionEventCoordinator._poll_once(self.app)
        self.assertFalse(self.app.live_active)
        self.app.show_version_check.assert_called_once_with()
        self.app.show_login.assert_not_called()
        check.assert_not_called()

    def test_no_worker_or_ui_source_calls_activation_or_invalidation(self):
        source = inspect.getsource(BackgroundVersionController)
        for forbidden in ('activate_for_official', 'prepare_dynamic_runtime', 'invalidate(', 'run_client('):
            self.assertNotIn(forbidden, source)

    def test_first_full_establishes_fresh_evidence_without_claiming_background_query(self):
        with patch('wlre.ui.background_version_controller.time.monotonic', return_value=200):
            self.assertTrue(self.app.can_login_after_version_check())
        self.assertEqual(self.app._observer_fresh_source, 'full')
        self.assertIsNone(self.app._observer_last_success)
        self.assertIn('尚未背景觀測', self.app._background_status.get())
        self.assertIn('完整檢查已建立識別基準', self.app._background_status.get())

    def test_new_match_renews_only_identifier_freshness_after_old_full_check(self):
        self.clock.advance(5000)
        original_result = self.app._version_gate_result
        self.deliver(self.result())
        with patch('wlre.ui.background_version_controller.time.monotonic', self.clock):
            self.assertTrue(self.app.can_login_after_version_check())
        self.assertEqual(self.app._version_gate_checked, 100)
        self.assertIs(self.app._version_gate_result, original_result)
        self.assertEqual(self.app._observer_fresh_at, 5000)
        self.assertEqual(self.app._observer_fresh_source, 'background')

    def test_stale_login_probe_success_requires_second_click_and_no_credentials_sent(self):
        self.clock.advance(301)
        with patch('wlre.ui.background_version_controller.time.monotonic', self.clock), \
             patch('wlre.ui.background_version_controller.threading.Thread') as thread, \
             patch('wlre.ui.version_gate_controller.messagebox'), \
             patch.object(self.app, 'start_version_check') as full, \
             patch('wlre.ui.gui.run_client') as client:
            self.assertFalse(self.app.can_login_after_version_check())
            self.assertFalse(self.app.can_login_after_version_check())
            self.assertEqual(thread.call_count, 1)
            worker = thread.call_args.kwargs['target']
            with patch('wlre.ui.background_version_controller.observe_background_versions', return_value=self.result()):
                worker()
            self.app.poll_background_versions()
            client.assert_not_called()
            self.assertTrue(self.app._version_gate_entry_approved)
            self.assertTrue(self.app.can_login_after_version_check())
            full.assert_not_called()
        self.assertEqual(self.app._version_gate_checked, 100)

    def test_configured_interval_controls_freshness_without_changing_full_stamp(self):
        self.app._observer_interval.set('60')
        self.app.apply_observer_interval()
        with patch('wlre.ui.background_version_controller.time.monotonic', return_value=60):
            self.assertTrue(self.app._observer_is_fresh())
        with patch('wlre.ui.background_version_controller.time.monotonic', return_value=60.001):
            self.assertFalse(self.app._observer_is_fresh())
        self.assertEqual(self.app._version_gate_checked, 100)
        self.assertIn('1 分鐘', self.app._background_status.get())

    def test_monitor_inflight_login_then_failure_holds_the_captured_new_session(self):
        from collections import deque
        worker = self.begin_worker()
        old_event = self.app._session_resource_hold
        self.app.assert_ui_thread = Mock()
        self.app.profile = {'fixture': True}
        self.app.worker = None
        self.app.account = Mock(get=Mock(return_value='fixture'))
        self.app.password = Mock(get=Mock(return_value='fixture'))
        self.app.port = Mock(get=Mock(return_value='16988'))
        self.app.host = Mock(get=Mock(return_value='example.invalid'))
        self.app.save_saved_login = Mock(return_value=True)
        self.app.background = Mock(return_value=True)
        self.app._background_logs = deque()
        for name in ('activate_account_settings', 'hide_all_features', 'update_role_choices',
                     'connection_monitor', 'connection_status', 'status', 'connect_button',
                     'chat_panel', 'log', 'efficiency_panel', 'companion_panel', 'expedition_panel',
                     'benefits_panel', 'other_features_panel', 'instance_panel', 'overview_panel'):
            setattr(self.app, name, Mock())
        with patch('wlre.ui.background_version_controller.time.monotonic', self.clock):
            App.connect(self.app)
        self.assertTrue(self.app.live_active)
        new_event = self.app._session_resource_hold
        self.assertIsNot(new_event, old_event)
        with patch('wlre.ui.background_version_controller.observe_background_versions', return_value=self.result(status='unverified')):
            worker()
        self.app.poll_background_versions()
        self.assertTrue(new_event.is_set())
        self.assertFalse(old_event.is_set())
        work = self.app.background.call_args.args[0]
        with patch('wlre.ui.gui.run_client') as client:
            work()
        self.assertIs(client.call_args.kwargs['resource_safety_hold'], new_event)
        self.assertIs(client.call_args.kwargs['verify_first'], True)

    def test_missing_full_anchor_cannot_create_initial_fresh_evidence(self):
        no_anchor = dict(self.full)
        no_anchor.pop('runtime_identity')
        self.app._background_full_check_started()
        self.app._background_full_check_finished(no_anchor, True)
        self.assertIsNone(self.app._observer_anchor)
        self.assertIsNone(self.app._observer_fresh_at)
        self.assertFalse(self.app._observer_is_fresh())
        self.app._version_gate_messages.put((self.app._version_gate_generation, no_anchor, self.clock()))
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, 'blocked')
        self.assertTrue(self.app._version_gate_result['blocked'])

    def test_idle_polls_do_not_reconfigure_buttons_or_add_timers(self):
        for name in ('_observer_retry_button', '_observer_disconnect_button',
                     '_observer_apply_button', '_observer_interval_input'):
            setattr(self.app, name, Mock())
        self.app._refresh_observer_controls()
        for _ in range(1000):
            self.app.poll_background_versions()
        self.assertEqual(self.app._observer_retry_button.configure.call_count, 1)
        self.assertEqual(self.app._observer_disconnect_button.configure.call_count, 1)
        self.app.root.after.assert_not_called()

    def test_late_mailbox_delivery_does_not_renew_freshness_from_delivery_time(self):
        worker = self.begin_worker()
        with patch('wlre.ui.background_version_controller.time.monotonic', self.clock), \
             patch('wlre.ui.background_version_controller.observe_background_versions', return_value=self.result()):
            worker()
        self.clock.advance(301)
        with patch('wlre.ui.background_version_controller.time.monotonic', self.clock), \
             patch('wlre.ui.background_version_controller.threading.Thread') as thread:
            self.app.poll_background_versions()
            self.assertFalse(self.app._observer_is_fresh())
            thread.assert_called_once()
        self.assertEqual(self.app._observer_state, 'stale')
        self.assertIsNone(self.app._observer_fresh_at)
        self.assertEqual(self.app._version_gate_checked, 100)

    def test_foreign_queue_token_does_not_clear_real_worker_busy_state(self):
        self.begin_worker()
        other = ObservationSchedule(clock=self.clock)
        self.app._background_messages.put((other.begin(), self.result(), self.clock()))
        self.app.poll_background_versions()
        self.assertTrue(self.app._background_busy)
        self.assertFalse(self.app._start_background_observation(force=True))
        self.assertIsNone(self.app._background_schedule.latest)

    def test_future_and_nonfinite_completion_time_cannot_grant_freshness(self):
        for stamp in (1, float('nan'), float('inf'), True, '0'):
            with self.subTest(stamp=stamp):
                token = self.app._background_schedule.begin(force=True)
                self.app._background_messages.put((token, self.result(), stamp))
                with patch('wlre.ui.background_version_controller.time.monotonic', self.clock), \
                     patch.object(self.app, '_start_background_observation'):
                    self.app.poll_background_versions()
                    self.assertFalse(self.app._observer_is_fresh())
                self.assertEqual(self.app._observer_state, 'stale')
                self.assertIsNone(self.app._observer_fresh_at)
                self.assertFalse(self.app._observer_requires_full_check)
                self.assertTrue(self.app._version_gate_entry_approved)

    def test_late_full_result_keeps_anchor_but_requires_fresh_light_evidence(self):
        self.app._version_gate_messages.put((self.app._version_gate_generation, self.full, 0))
        self.clock.advance(301)
        with patch('wlre.ui.background_version_controller.time.monotonic', self.clock), \
             patch('wlre.ui.background_version_controller.threading.Thread') as thread:
            self.app.drain_version_checks()
            self.assertEqual(self.app.version_gate_state, 'ready')
            self.assertFalse(self.app._observer_is_fresh())
            self.assertEqual(self.app._observer_anchor, self.anchor)
            self.assertEqual(self.app._observer_state, 'stale')
            self.app.poll_background_versions()
            self.assertEqual(thread.call_args.kwargs['name'], 'background-version-observer')

    def test_queued_bad_observation_wins_over_login_click_before_normal_poll(self):
        for bad in (self.result(status='unverified'),
                    self.result(official=replace(self.anchor, data_ver='1.3.23.0'),
                                database=replace(self.anchor, data_ver='1.3.23.0'))):
            with self.subTest(status=bad.status):
                self.app._background_full_check_finished(self.full, True)
                self.app._version_gate_result = self.full
                self.app._version_gate_entry_approved = True
                self.app.version_gate_state = 'ready'
                token = self.app._background_schedule.begin(force=True)
                self.app._background_messages.put((token, bad, self.clock()))
                self.app.assert_ui_thread = Mock()
                with patch('wlre.ui.version_gate_controller.messagebox'), \
                     patch('wlre.ui.gui.run_client') as client, \
                     patch('wlre.ui.background_version_controller.threading.Thread') as thread:
                    App.connect(self.app)
                    client.assert_not_called()
                    thread.assert_not_called()
                self.assertTrue(self.app._observer_requires_full_check)
                self.assertIsNone(self.app._version_gate_result)
                self.assertFalse(self.app._version_gate_entry_approved)

    def test_observation_arriving_during_account_storage_is_checked_before_network(self):
        self.app.assert_ui_thread = Mock()
        self.app.profile = {'fixture': True}
        self.app.worker = None
        self.app.account = Mock(get=Mock(return_value='fixture'))
        self.app.password = Mock(get=Mock(return_value='fixture'))
        self.app.port = Mock(get=Mock(return_value='16988'))
        self.app.host = Mock(get=Mock(return_value='example.invalid'))
        self.app.activate_account_settings = Mock()
        token = self.app._background_schedule.begin(force=True)
        def save():
            self.app._background_messages.put((token, self.result(status='unverified'), self.clock()))
            return True
        self.app.save_saved_login = Mock(side_effect=save)
        with patch('wlre.ui.background_version_controller.time.monotonic', self.clock), \
             patch('wlre.ui.version_gate_controller.messagebox'), \
             patch('wlre.ui.gui.run_client') as client:
            App.connect(self.app)
        client.assert_not_called()
        self.app.password.set.assert_not_called()
        self.assertTrue(self.app._observer_requires_full_check)

    def test_invalid_full_completion_evidence_is_not_replaced_with_drain_time(self):
        for stamp in (None, True, float('nan'), float('inf'), 1):
            with self.subTest(stamp=stamp), \
                 patch('wlre.ui.background_version_controller.time.monotonic', self.clock):
                self.app._background_full_check_finished(self.full, True, completed_at=stamp)
                self.assertIsNone(self.app._observer_fresh_at)
                self.assertFalse(self.app._observer_is_fresh())
                self.assertEqual(self.app._observer_state, 'stale')
