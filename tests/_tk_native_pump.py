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
    # 最小測試視窗也必須遵循正式桌面的擁有者清理，不能將 Tcl 留給背景 GC。
    from wlre.ui.resource_lifetime import install_root_lifetime
    root = NativeTestRoot()
    install_root_lifetime(root)
    return root


def assert_normal_display(testcase, window):
    """Aqua 對 min=max 的固定窗可回報 zoomed；仍須證明固定且實際可見。"""
    if window.tk.call('tk', 'windowingsystem') == 'aqua' and window.state() == 'zoomed':
        testcase.assertEqual(tuple(map(int, window.resizable())), (0, 0))
        testcase.assertEqual(window.minsize(), window.maxsize())
    else:
        testcase.assertEqual(window.state(), 'normal')
    testcase.assertTrue(window.winfo_ismapped())
