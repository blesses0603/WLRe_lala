"""Root 關閉後的原生參照必須在 UI 執行緒解除，背景 GC 不可再碰 Tcl。"""
import gc
import os
import subprocess
import sys
import tkinter as tk
import unittest
from pathlib import Path
from threading import Thread

from _tk_native_pump import create_root
from PIL import Image, ImageTk

from wlre.ui.resource_lifetime import install_root_lifetime


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin', '需要桌面顯示環境')
class UiResourceLifetimeTests(unittest.TestCase):
    def test_owned_resources_release_without_touching_another_interpreter(self):
        first, second = create_root(), create_root()
        install_root_lifetime(first)
        install_root_lifetime(second)
        one = tk.StringVar(first, value='one')
        two = tk.StringVar(second, value='two')
        image = ImageTk.PhotoImage(Image.new('RGBA', (2, 2)), master=first)
        one.trace_add('write', lambda *_: one.get())
        first.destroy()
        self.assertIsNone(one._tk)
        self.assertEqual(two.get(), 'two')
        with self.assertRaises(tk.TclError):
            image.tk.call('info', 'exists', one._name)
        self.assertTrue(second.winfo_exists())
        second.destroy()

    def test_wrong_thread_destroy_is_rejected_before_calling_tcl(self):
        root, rejected = create_root(), []
        install_root_lifetime(root)

        def bad_close():
            try:
                root.destroy()
            except RuntimeError:
                rejected.append(True)

        thread = Thread(target=bad_close)
        thread.start()
        thread.join(2)
        self.assertEqual(rejected, [True])
        self.assertTrue(root.winfo_exists())
        root.destroy()

    def test_retained_destroy_callback_does_not_keep_native_interpreter(self):
        script = """
import gc, tkinter as tk
from threading import Thread
from types import SimpleNamespace
from wlre.ui.resource_lifetime import install_root_lifetime
gc.disable()
def cycle():
    root = tk.Tk()
    install_root_lifetime(root)
    saved = root.destroy
    saved(); saved()
    holder = SimpleNamespace(cleanup=saved)
    holder.self = holder
cycle()
worker = Thread(target=gc.collect)
worker.start(); worker.join(10)
if worker.is_alive():
    raise RuntimeError('retained cleanup did not release')
print('retained cleanup owner release passed')
"""
        result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                                text=True, timeout=20, check=False,
                                cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('retained cleanup owner release passed', result.stdout)

    def test_background_gc_after_close_in_isolated_process(self):
        # 若回歸成 Tcl_AsyncDelete，僅讓子程序失敗，不擊落整套測試。
        script = '''
import gc, sys, tkinter as tk
from threading import Thread
from types import SimpleNamespace
from PIL import Image, ImageTk
from wlre.ui.resource_lifetime import install_root_lifetime
gc.disable()
def make_cycle():
    root = tk.Tk()
    install_root_lifetime(root)
    variable = tk.StringVar(root, value='lifecycle-test')
    variable.trace_add('write', lambda *_: variable.get())
    image = ImageTk.PhotoImage(Image.new('RGBA', (2, 2)), master=root)
    cycle = SimpleNamespace(root=root, variable=variable, image=image)
    cycle.self = cycle
    root.destroy()
make_cycle()
from unittest.mock import patch
from wlre.ui.application_host import DesktopHost
def make_desktop_cycle():
    with patch('wlre.ui.version_gate_controller.VersionGateController.start_version_check'):
        root = tk.Tk()
        host = DesktopHost(root)
        host.start(); root.update_idletasks(); host.request_close()
make_desktop_cycle()
errors = []
sys.unraisablehook = errors.append
worker = Thread(target=gc.collect)
worker.start(); worker.join(10)
if worker.is_alive() or errors:
    raise RuntimeError('background GC touched disposed UI resources')
print('owner-thread cleanup passed')
'''
        result = subprocess.run([sys.executable, '-c', script],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('owner-thread cleanup passed', result.stdout)
        # 保持本測試的其他 Python 資源也在擁有者回收。
        gc.collect()
