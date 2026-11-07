"""Tk-thread presentation for read-only, periodic version identifier hints.

Only the full gate establishes Runtime authority and its full-check stamp.
Identifier observations may refresh separate evidence, never content validation.
A bad observation revokes entry and latches the current session's separate hold.
"""
from datetime import datetime, timezone
from wlre.ui.display_time import DISPLAY_TIMEZONE
import os
import math
import queue
import re
import time
import threading
import tkinter as tk
from tkinter import ttk

from wlre.services.background_version_observer import (
    ObservationResult, ObservationSchedule, observe_background_versions,
    version_identifiers_from_database,
)


_UNSET_COMPLETED_AT = object()

def _unknown_observation():
    return ObservationResult('unverified', 'observation_unavailable', None, None,
                             datetime.now(timezone.utc).isoformat(timespec='seconds'))


def _observation_time(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            return '尚無'
        return stamp.astimezone(DISPLAY_TIMEZONE).strftime('%m-%d %H:%M:%S UTC+8')
    except (AttributeError, TypeError, ValueError):
        return '尚無'


def _display_identifier(value):
    # Display only bounded identifier grammar, never raw error/path content.
    return value if isinstance(value, str) and re.fullmatch(r'[0-9A-Za-z_.-]{1,96}', value) else '未知'


class BackgroundVersionController:
    def initialize_background_observer(self):
        self._background_schedule = ObservationSchedule(
            os.environ.get('WLRE_VERSION_OBSERVE_INTERVAL_SECONDS', 300), initial_delay=True)
        self._background_messages = queue.SimpleQueue()
        self._background_busy = False
        self._background_closed = False
        self._background_probe_due = False
        self._observer_anchor = None
        self._observer_last_success = None
        self._observer_fresh_at = None
        self._observer_fresh_source = None
        self._observer_requires_full_check = False
        self._observer_alarm = False
        self._observer_state = 'pending'
        self._observer_interval = tk.StringVar(value=f'{self._background_schedule.interval_seconds:g}')
        self._background_status = tk.StringVar(value='')
        self._background_summary = tk.StringVar(value='')
        BackgroundVersionController._update_observer_text(self)

    def build_background_observer_controls(self, parent):
        self._background_label = ttk.Label(
            parent, textvariable=self._background_status, style='Muted.TLabel',
            justify='left', wraplength=900)
        self._background_label.pack(fill='x', pady=(0, 5))
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=(0, 8))
        ttk.Label(row, text='背景輪詢間隔（秒，本次）').pack(side='left')
        self._observer_interval_input = ttk.Spinbox(
            row, from_=60, to=3600, increment=60, width=6,
            textvariable=self._observer_interval)
        self._observer_interval_input.pack(side='left', padx=(5, 4))
        self._observer_apply_button = ttk.Button(row, text='套用', command=self.apply_observer_interval)
        self._observer_apply_button.pack(side='left')
        self._observer_retry_button = ttk.Button(row, text='重新觀測識別', command=self.recheck_background_versions)
        self._observer_retry_button.pack(side='left', padx=8)
        self._observer_disconnect_button = ttk.Button(row, text='安全中斷連線', command=self.stop)
        self._observer_disconnect_button.pack(side='right')
        self._observer_controls_state = None
        self._refresh_observer_controls()

    def apply_observer_interval(self):
        if self._background_closed:
            return
        value = self._background_schedule.set_interval(self._observer_interval.get())
        self._observer_interval.set(f'{value:g}')
        self._update_observer_text()
        self._set_login_gate_button()

    def _evidence_is_fresh(self, completed_at):
        if type(completed_at) not in (int, float) or not math.isfinite(completed_at):
            return False
        age = time.monotonic() - completed_at
        return 0 <= age <= self._background_schedule.interval_seconds

    def _observer_is_fresh(self):
        result = self._version_gate_result or {}
        if (self._observer_requires_full_check or self._observer_fresh_at is None
                or self._observer_anchor is None
                or version_identifiers_from_database(result.get('runtime_identity')) != self._observer_anchor):
            return False
        return self._evidence_is_fresh(self._observer_fresh_at)

    def _update_observer_text(self):
        interval = self._background_schedule.interval_seconds
        cadence = f'{interval / 60:g} 分鐘' if interval % 60 == 0 else f'{interval:g} 秒'
        state = {
            'pending': ('本次完整檢查已建立識別基準；尚未背景觀測'
                        if self._observer_fresh_source == 'full' else '尚未背景觀測'),
            'match': '識別相符（僅識別，非內容驗證）',
            'different': '官方與資料庫識別不一致',
            'changed': '識別已變更，與本次完整驗證不同',
            'unknown': '查詢失敗／識別未知',
            'no_anchor': '尚無完整驗證識別基準',
            'stale': '觀測回應已過期或時間無效，須重新觀測',
        }[self._observer_state]
        if self._observer_requires_full_check and self._observer_state == 'match':
            state += '；先前異常仍須完整檢查'
        success = _observation_time(self._observer_last_success)
        running = '｜查詢中' if self._background_busy else ''
        backoff = ('｜失敗後有界退避重試' if self._background_schedule.failure_count else '')
        self._background_status.set(
            f'背景每 {cadence} 輪詢（非推播）{running}{backoff}｜上次成功觀測：{success}\n{state}；不重驗內容，無法偵測同版內容替換。')
        self._background_summary.set(
            f'背景版本：{state}｜{cadence} 輪詢，非推播｜上次成功：{success}')

    def _refresh_observer_controls(self):
        if not hasattr(self, '_observer_retry_button'):
            return
        try:
            if not self._observer_retry_button.winfo_exists():
                return
        except tk.TclError:
            return
        closing = self._background_closed or self._closing or self._startup_exit_requested.is_set()
        checking = self.version_gate_state == 'checking'
        state = (closing, self._background_busy, checking, self.live_active)
        if state == getattr(self, '_observer_controls_state', None):
            return
        self._observer_controls_state = state
        self._observer_retry_button.configure(state='disabled' if (
            closing or self._background_busy or checking) else 'normal')
        self._observer_disconnect_button.configure(state='normal' if self.live_active and not closing else 'disabled')
        self._observer_apply_button.configure(state='disabled' if closing else 'normal')
        self._observer_interval_input.configure(state='disabled' if closing else 'normal')

    def recheck_background_versions(self):
        self._start_background_observation(force=True)

    def _start_background_observation(self, *, force=False):
        if (self._background_closed or self._closing or self._startup_exit_requested.is_set()
                or self.version_gate_state == 'checking'):
            return False
        token = self._background_schedule.begin(force=force)
        if token is None:
            return False
        self._background_busy = True
        self._update_observer_text()
        self._refresh_observer_controls()
        messages = self._background_messages

        def worker():
            # Plain immutable result + mailbox only. No Tk/App reference.
            try:
                result = observe_background_versions()
            except Exception:
                result = _unknown_observation()
            messages.put((token, result, time.monotonic()))

        try:
            threading.Thread(target=worker, name='background-version-observer', daemon=True).start()
        except RuntimeError:
            messages.put((token, _unknown_observation(), time.monotonic()))
        return True

    def poll_background_versions(self, *, start_due=True):
        while True:
            try:
                token, result, completed_at = self._background_messages.get_nowait()
            except queue.Empty:
                break
            accepted = self._background_schedule.finish(token, result)
            self._background_busy = (not self._background_closed and
                                     self._background_schedule.seconds_until_due() is None)
            if not accepted:
                continue
            if self._background_closed or self._closing or self._startup_exit_requested.is_set():
                continue
            result = self._background_schedule.latest
            if result.status != 'unverified':
                self._observer_last_success = result.checked_at_utc
            if result.status == 'unverified':
                state = 'unknown'
            elif result.status != 'identifiers_match' or result.official != result.database:
                state = 'different'
            elif self._observer_anchor is None:
                state = 'no_anchor'
            elif result.official != self._observer_anchor:
                state = 'changed'
            elif not self._evidence_is_fresh(completed_at):
                state = 'stale'
            else:
                state = 'match'
            self._observer_state = state
            if state not in ('match', 'stale'):
                self._observer_fresh_at = None
                self._observer_fresh_source = None
                self._observer_requires_full_check = True
                self._observer_alarm = True
                self._version_gate_entry_approved = False
                self._version_gate_result = None
                # Keep the full-gate timestamp untouched: this is not a check.
                self.version_gate_state = 'blocked'
                hold = getattr(self, '_session_resource_hold', None)
                if self.live_active and hold is not None:
                    hold.set()
            elif state == 'stale':
                self._observer_fresh_at = None
                self._observer_fresh_source = None
                self._background_probe_due = True
            elif not self._observer_requires_full_check:
                # UI backlog must not turn an old network response into fresh
                # evidence. This monotonic stamp was captured by the worker.
                self._observer_fresh_at = completed_at
                self._observer_fresh_source = 'background'
            self._update_observer_text()
            self._set_login_gate_button()
            if self._observer_alarm:
                self.show_version_check()
        self._refresh_observer_controls()
        if start_due and self._start_background_observation(force=self._background_probe_due):
            self._background_probe_due = False

    def _background_full_check_started(self):
        self._background_schedule.supersede()
        self._background_probe_due = False
        self._observer_anchor = None
        self._observer_fresh_at = None
        self._observer_fresh_source = None
        self._observer_alarm = False
        self._refresh_observer_controls()

    def _background_full_check_finished(self, result, verified, *, completed_at=_UNSET_COMPLETED_AT):
        anchor = version_identifiers_from_database(result.get('runtime_identity')) if verified else None
        self._observer_anchor = anchor
        self._background_schedule.supersede(baseline=anchor)
        if verified and anchor is not None:
            stamp = time.monotonic() if completed_at is _UNSET_COMPLETED_AT else completed_at
            self._observer_fresh_at = stamp if self._evidence_is_fresh(stamp) else None
            self._observer_fresh_source = 'full'
            self._observer_requires_full_check = False
            self._observer_alarm = False
            self._observer_state = 'pending' if self._observer_fresh_at is not None else 'stale'
            self._background_probe_due = self._observer_fresh_at is None
        else:
            self._observer_fresh_at = None
            self._observer_fresh_source = None
        self._update_observer_text()
        self._refresh_observer_controls()

    def _render_background_alarm(self):
        if not self._observer_alarm or self.version_gate_state == 'checking':
            return False
        self._version_heading.set('背景識別尚未確認 · 必須重新完整檢查')
        self.version_gate_text.set(
            '已要求暫停新的資料依賴動作，連線保持；請先安全中斷，再完整檢查。' if self.live_active else
            '已阻擋新的登入與重連；即使識別恢復相同，仍須完整檢查後才能登入。')
        latest = self._background_schedule.latest
        official = latest.official if latest is not None else None
        database = latest.database if latest is not None else None
        def value(identifiers, field):
            return _display_identifier(getattr(identifiers, field, None))
        self._version_main.set(f'官方 {value(official, "main_package")}｜資料庫 {value(database, "main_package")}')
        self._version_data.set(f'官方 {value(official, "data_package")}｜資料庫 {value(database, "data_package")}')
        self._version_path.set(f'官方 EXE {value(official, "exe_version")} / DataVer {value(official, "data_ver")}')
        self._version_baseline.set(
            f'Data {value(self._observer_anchor, "data_package")}｜Main {value(self._observer_anchor, "main_package")}')
        self._version_remote.set(
            f'本次 Runtime：EXE {value(self._observer_anchor, "exe_version")} / DataVer {value(self._observer_anchor, "data_ver")}；舊授權已撤銷。')
        self._startup_elapsed.set('背景比對不重驗內容；異常後須重新完整檢查，不能只靠版號恢復。')
        self._version_progress.finish()
        self._version_continue_button.configure(text='禁止登入', state='disabled')
        self._version_retry_button.configure(
            text='斷線後完整檢查' if self.live_active else '重新完整檢查',
            state='disabled' if self.live_active else 'normal')
        self._version_footer_hint.configure(text='「重新觀測識別」只做唯讀查詢；關閉此視窗會依原規則結束程式，不解除安全暫停。')
        self._refresh_observer_controls()
        return True

    def close_background_observer(self):
        if not getattr(self, '_background_closed', True):
            self._background_closed = True
            self._background_schedule.close()
            self._refresh_observer_controls()
