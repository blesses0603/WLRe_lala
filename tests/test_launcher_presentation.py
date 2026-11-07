"""Offline presentation regressions; canvas tests also run on Windows CI."""
import os
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock

from wlre.launcher_progress import (
    _ACCENT, _TRACK, _CyanProgress, _ProgressMailbox, _format_stage,
    _progress_counts,
)


class LauncherPresentationTests(unittest.TestCase):
    def test_only_valid_known_stage_counts_become_determinate(self):
        for phase in ('bundle_item', 'raw_resource_item'):
            self.assertEqual(_progress_counts(phase, {'completed': 8, 'total': 24}), (8, 24))
            for done, total in ((True, 2), (1, False), (-1, 2), (3, 2),
                                (0, 0), ('1', 2), (1, 1000001)):
                self.assertIsNone(_progress_counts(phase, {'completed': done, 'total': total}))
        self.assertIsNone(_progress_counts('runtime_bundle_plan', {'completed': 8, 'total': 24}))
        self.assertIsNone(_progress_counts('bundle_item', None))
        self.assertEqual(_format_stage('runtime_bundle_plan'), '準備必要資源')
        self.assertEqual(_format_stage('runtime_identity_verified'), '核對官方版本')

    def test_burst_coalesces_without_losing_failure_or_terminal_receipt(self):
        mailbox = _ProgressMailbox()
        receipt = {'status': 'error', 'assets_ready': False, 'can_send_packets': False}
        def producer():
            mailbox.report('extract_failed', {'feature': 'npc', 'stage': 'Eve 二進位事件'})
            for done in range(100001):
                mailbox.report('bundle_item', {'completed': done, 'total': 100000})
            mailbox.report('untrusted-phase', {'path': 'secret'})
            mailbox.finish(receipt)
        worker = threading.Thread(target=producer)
        worker.start()
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), 'Producer must never wait for the UI to drain')
        update, failure, terminal = mailbox.take()
        self.assertEqual(update[2], (100000, 100000))
        self.assertIn('Eve 二進位事件', failure)
        self.assertIs(terminal[0], receipt)
        self.assertEqual(mailbox.take(), (None, None, None))

    def test_official_server_list_phases_are_displayed_without_granting_login(self):
        mailbox = _ProgressMailbox()
        for phase in ('server_list_ready', 'server_list_unavailable'):
            mailbox.report(phase, {'path': 'private value'})
            update, failure, terminal = mailbox.take()
            self.assertEqual(update[0], '同步官方伺服器清單')
            self.assertNotIn('private value', update[1])
            self.assertIsNone(update[2])
            self.assertIsNone(terminal)

    def test_zero_and_complete_stage_counts_are_preserved(self):
        mailbox = _ProgressMailbox()
        for done in (0, 24):
            mailbox.report('bundle_item', {'completed': done, 'total': 24})
            self.assertEqual(mailbox.take()[0][2], (done, 24))
        mailbox.report('manifest', {'package': 'DataPackage'})
        self.assertIsNone(mailbox.take()[0][2])

    def test_native_themes_cannot_override_canvas_colors_or_create_extra_timers(self):
        tk = Mock()
        canvas = tk.Canvas.return_value
        canvas.winfo_width.return_value = 300
        canvas.after.return_value = 'timer-1'
        bar = _CyanProgress(object(), tk)
        self.assertEqual(tk.Canvas.call_args.kwargs['bg'], _TRACK)
        self.assertEqual(canvas.create_rectangle.call_args.kwargs['fill'], _ACCENT)
        self.assertEqual(canvas.after.call_count, 1)
        for _ in range(20):
            bar.set_counts(None)
        self.assertEqual(canvas.after.call_count, 1)
        bar.set_counts((8, 24))
        self.assertEqual(canvas.coords.call_args.args[1:], (0, 0, 100, 8))
        canvas.after_cancel.assert_called_once_with('timer-1')
        bar.set_counts((0, 24))
        self.assertEqual(canvas.coords.call_args.args[3], 0)
        bar.set_counts(None)
        self.assertEqual(canvas.after.call_count, 2)
        bar.stop()
        bar.stop()
        self.assertEqual(canvas.after_cancel.call_count, 2)
        # A late timer invocation after stop may not schedule another callback.
        bar._tick()
        self.assertEqual(canvas.after.call_count, 2)

    @unittest.skipUnless(os.name == 'nt' or bool(os.environ.get('DISPLAY')),
                         'Requires an active desktop / Xvfb')
    def test_real_tk_colors_resize_safe_close_failure_and_burst(self):
        code = r'''
import time
import tkinter as tk
from tkinter import ttk
from wlre.launcher_progress import run_with_progress, _ACCENT, _TRACK
original_tk = tk.Tk
checks = []
errors = []

def make_root():
    root = original_tk()
    root.report_callback_exception = lambda *args: errors.append(str(args))
    def inspect():
        try:
            widgets = []
            def walk(widget):
                widgets.append(widget)
                for child in widget.winfo_children():
                    walk(child)
            walk(root)
            bars = [w for w in widgets if isinstance(w, tk.Canvas)]
            assert len(bars) == 1
            bar = bars[0]
            # Under every installed theme, the indicator remains explicitly cyan.
            style = ttk.Style(root)
            for theme in style.theme_names():
                style.theme_use(theme)
                assert bar.cget('background') == _TRACK
                assert bar.itemcget(bar.find_all()[0], 'fill') == _ACCENT
            root.geometry('540x352')
            root.update_idletasks()
            # Both clicks retain the worker and window, matching existing semantics.
            root.tk.call(root.protocol('WM_DELETE_WINDOW'))
            root.tk.call(root.protocol('WM_DELETE_WINDOW'))
            assert root.winfo_exists()
            checks.append('checked')
        except Exception as exc:
            errors.append(repr(exc))
    root.after(100, inspect)
    return root

tk.Tk = make_root

def task(*, progress):
    progress('runtime_bundle_plan', {})
    time.sleep(.25)
    progress('extract_failed', {'feature': 'npc', 'stage': 'Eve 二進位事件'})
    for i in range(10001):
        progress('bundle_item', {'completed': i, 'total': 10000})
    time.sleep(.15)
    raise RuntimeError('private path should not be rendered')

result = run_with_progress(task)
assert checks == ['checked'], checks
assert not errors, errors
assert result == {'status': 'error', 'assets_ready': False, 'can_send_packets': False}
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                                text=True, encoding='utf-8', timeout=20,
                                env=dict(os.environ, WLRE_DISABLE_AUTO_CATALOG=''))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.name == 'nt' or bool(os.environ.get('DISPLAY')),
                         'Requires an active desktop / Xvfb')
    def test_real_tk_long_stages_and_terminal_text_fit_at_each_dpi(self):
        code = r'''
import sys
import threading
import tkinter as tk
from unittest.mock import patch
from wlre.launcher_progress import run_with_progress, _ProgressMailbox

original_tk = tk.Tk
original_take = _ProgressMailbox.take
roots = []
checks = []
errors = []
release_worker = threading.Event()

def make_root():
    root = original_tk()
    root.tk.call('tk', 'scaling', float(sys.argv[1]))
    root.report_callback_exception = lambda *args: errors.append(str(args))
    roots.append(root)
    return root

def check_visible(name):
    root = roots[0]
    root.update_idletasks()
    widgets = []
    def walk(widget):
        if isinstance(widget, (tk.Label, tk.Canvas)):
            widgets.append(widget)
        for child in widget.winfo_children():
            walk(child)
    walk(root)
    assert len([w for w in widgets if isinstance(w, tk.Canvas)]) == 1
    for widget in widgets:
        variable = widget.cget('textvariable') if isinstance(widget, tk.Label) else ''
        text = root.globalgetvar(variable) if variable else str(widget)
        assert widget.winfo_ismapped(), (name, 'hidden', text)
        assert widget.winfo_height() >= widget.winfo_reqheight(), (
            name, 'clipped height', text, widget.winfo_height(), widget.winfo_reqheight())
        top = widget.winfo_rooty() - root.winfo_rooty()
        assert 0 <= top and top + widget.winfo_height() <= root.winfo_height(), (
            name, 'outside window', text)
    checks.append(name)

def terminal_check():
    try:
        check_visible('terminal')
    except Exception as exc:
        errors.append(repr(exc))

def close_check():
    try:
        check_visible('close')
    except Exception as exc:
        errors.append(repr(exc))
    finally:
        release_worker.set()

def narrow_check():
    try:
        check_visible('narrow')
        root = roots[0]
        root.tk.call(root.protocol('WM_DELETE_WINDOW'))
        root.tk.call(root.protocol('WM_DELETE_WINDOW'))
        root.after(150, close_check)
    except Exception as exc:
        errors.append(repr(exc))
        release_worker.set()

def initial_check():
    try:
        check_visible('initial')
        root = roots[0]
        # A resize request must respect the DPI/content-aware minimum size.
        root.geometry('540x352')
        root.after(150, narrow_check)
    except Exception as exc:
        errors.append(repr(exc))
        release_worker.set()

def take(mailbox):
    snapshot = original_take(mailbox)
    if snapshot[0] is not None:
        # Start only after the actual long stage reaches the main-thread pump.
        roots[0].after(150, initial_check)
    if snapshot[2] is not None:
        roots[0].after(150, terminal_check)
    return snapshot

def task(*, progress):
    progress('raw_rebuild_ready', {
        'completed': 21767, 'total': 21767, 'formal_blockers': ['a', 'b']})
    assert release_worker.wait(8), 'UI checks did not release the worker'
    return {'status': 'error', 'assets_ready': False, 'can_send_packets': False}

with patch.object(tk, 'Tk', make_root), patch.object(_ProgressMailbox, 'take', take):
    result = run_with_progress(task)
assert not errors, errors
assert checks == ['initial', 'narrow', 'close', 'terminal'], checks
assert result == {'status': 'error', 'assets_ready': False, 'can_send_packets': False}
'''
        for scaling in ('1.333333', '2.0', '2.666667'):
            with self.subTest(scaling=scaling):
                result = subprocess.run(
                    [sys.executable, '-c', code, scaling], capture_output=True,
                    text=True, encoding='utf-8', timeout=20,
                    env=dict(os.environ, WLRE_DISABLE_AUTO_CATALOG=''))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
