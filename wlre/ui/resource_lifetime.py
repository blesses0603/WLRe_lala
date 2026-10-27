"""在 UI 擁有者執行緒釋放已銷毀 interpreter 的 Python 包裝資源。

Tk Variable 沒有公開 dispose；僅 destroy 視窗仍可能留下循環參照，
其 __del__ 若稍後由背景 GC 執行，會造成 Tcl_AsyncDelete。此處只在
整個 Tk root 已 destroy 後解除其原生參照，不影響其他 interpreter。
"""
import gc
import tkinter as tk
from threading import get_ident
from tkinter import font as tkfont
from tkinter import ttk

from PIL import ImageTk


class _ClosedInterpreter:
    def __getattr__(self, name):
        return self._closed

    @staticmethod
    def _closed(*args, **kwargs):
        raise tk.TclError('application has been destroyed')


_CLOSED = _ClosedInterpreter()


def _release(interpreter):
    """只辨識已知 Tk 包裝型別，不讀取變數值或任意物件屬性。"""
    objects = gc.get_objects()
    for value in objects:
        kind = type(value)
        if issubclass(kind, tk.Variable) and value.__dict__.get('_tk') is interpreter:
            try:
                for modes, name in value.trace_info():
                    value.trace_remove(modes, name)
                if interpreter.getboolean(interpreter.call('info', 'exists', value._name)):
                    interpreter.globalunsetvar(value._name)
            except tk.TclError:
                # Root 已銷毀，部分 Tcl 命令可能先由 widget 釋放。
                pass
            # CPython 3.12 Variable.__del__ 明確檢查 _tk is None。
            value._tk = None
            value._root = None
            value._tclCommands = None
        elif issubclass(kind, tk.Image) and value.__dict__.get('tk') is interpreter:
            try:
                interpreter.call('image', 'delete', value.name)
            except tk.TclError:
                pass
            value.name = None
            value.tk = _CLOSED
        elif issubclass(kind, (ImageTk.PhotoImage, ImageTk.BitmapImage)):
            if value.__dict__.get('tk') is interpreter:
                value.tk = _CLOSED
        elif issubclass(kind, tkfont.Font) and value.__dict__.get('_tk') is interpreter:
            if value.delete_font:
                try:
                    interpreter.call('font', 'delete', value.name)
                except tk.TclError:
                    pass
            value.delete_font = False
            value._tk = _CLOSED
            value._call = _CLOSED.call
            value._split = _CLOSED.splitlist
        elif issubclass(kind, (tk.Misc, ttk.Style)):
            if value.__dict__.get('tk') is interpreter:
                value.tk = _CLOSED


def install_root_lifetime(root):
    """只安裝於完整 Tk root；Toplevel 關閉不可釋放其他視窗的資源。"""
    if not isinstance(root, tk.Tk) or getattr(root, '_lala_lifetime_installed', False):
        return
    root._lala_lifetime_installed = True
    owner, interpreter, original = get_ident(), root.tk, root.destroy

    def destroy():
        nonlocal interpreter, original
        if get_ident() != owner:
            raise RuntimeError('Tk root must be destroyed by its owning thread')
        if interpreter is None:
            return None
        try:
            # Aqua 銷毀原生視窗可能重入事件迴圈，先取消 timer，避免關閉途中啟動新工作。
            for job in interpreter.call('after', 'info'):
                interpreter.call('after', 'cancel', job)
            return original()
        finally:
            # 不讓 root 的覆寫方法繼續保留原生 interpreter 於 closure。
            root.__dict__.pop('destroy', None)
            try:
                _release(interpreter)
            finally:
                # ExitStack／測試清理可繼續持有本回呼，不能讓閉包保留原生指標。
                interpreter = original = None

    root.destroy = destroy
