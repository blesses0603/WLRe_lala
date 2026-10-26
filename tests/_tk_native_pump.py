"""測試專用真實 Tk root；Aqua 以有界主迴圈取代可能卡住的 update。"""
import tkinter as tk


def pump_native_events(root):
    """執行真正的 Tk／Cocoa callback，不以 idle-only 或假畫面代替。"""
    if getattr(root, '_test_event_pumping', False):
        raise RuntimeError('native_test_event_loop_reentered')
    root._test_event_pumping = True
    job = None
    try:
        root.update_idletasks()
        job = root.after(25, root.quit)
        root.mainloop()
        try:
            exists = root.winfo_exists()
        except tk.TclError:
            exists = False  # callback 正常銷毀 root 後，沒有可更新的 interpreter。
        if exists:
            root.update_idletasks()
    finally:
        if job is not None:
            try:
                root.after_cancel(job)
            except tk.TclError:
                pass
        root._test_event_pumping = False


class NativeTestRoot(tk.Tk):
    def update(self):
        if self.tk.call('tk', 'windowingsystem') == 'aqua':
            return pump_native_events(self)
        return super().update()


def create_root():
    return NativeTestRoot()
