"""Direct Nuitka entry point: no child Python process or dependency installer."""
import os
from pathlib import Path
import sys
import traceback


def self_test():
    import tkinter
    from PIL import Image,ImageTk
    from wlre.ui import gui
    assert callable(gui.main)
    from wlre.paths import RESOURCE_ROOT
    from wlre.resource_manifest import validate_resources
    validate_resources(RESOURCE_ROOT)
    assert callable(ImageTk.PhotoImage) and tkinter.TkVersion>=8.6
    return 0


def smoke_test_gui():
    """Exercise bundled Tcl/Tk and the dashboard without any game connection."""
    self_test()
    import tkinter as tk
    from wlre.ui.gui import App
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    try:
        app = App(root)
        app.show_main()
        # In unattended macOS runners Cocoa's full event pump can block
        # on hidden Toplevel transitions. This entry-point smoke check needs
        # initial widget geometry, not an unbounded live event loop.
        # Windows/Linux unit tests exercise real Map/Configure callbacks.
        root.update_idletasks()
        if errors:
            raise RuntimeError('GUI callback failed: ' + str(errors))
        if not app.overview_panel.winfo_ismapped():
            raise RuntimeError('Dashboard was not mapped')
    finally:
        for job in root.tk.call('after', 'info'):
            # Cancel timers without deleting commands owned by child widgets.
            # Their destroy methods perform the command cleanup themselves.
            root.tk.call('after', 'cancel', job)
        root.destroy()
    if errors:
        raise RuntimeError('GUI callback failed during cleanup: ' + str(errors))
    return 0


def main():
    from wlre.storage.paths import error_log_file
    log_dir=error_log_file().parent
    log_dir.mkdir(parents=True,exist_ok=True)
    # Console-less EXEs still keep Tk callback errors and startup tracebacks.
    log=log_dir/'error.log'
    if sys.stderr is None:sys.stderr=log.open('a',encoding='utf8',buffering=1)
    try:
        if '--smoke-test-gui' in sys.argv:return smoke_test_gui()
        if '--self-test' in sys.argv:return self_test()
        if os.name=='nt':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('WLRE.Client.ByChiNing')
        from wlre.ui.gui import main as run_gui
        run_gui()
        return 0
    except Exception:
        details=traceback.format_exc()
        with log.open('a',encoding='utf8') as stream:stream.write(details+'\n')
        if not any(flag in sys.argv for flag in ('--self-test','--smoke-test-gui')) and os.name=='nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,'程式啟動失敗，詳細記錄：\n'+str(log),'飄流Re:LaLa  =By赤寧=',0x10)
        elif sys.stderr:print(details,file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
