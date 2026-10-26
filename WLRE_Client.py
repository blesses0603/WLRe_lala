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


def self_test_unityfs():
    """Verify the compiled executable ships UnityPy and its native codecs.

    This runs offline with no game files, user credentials or official CDN.
    A successful result proves bundled module/codec load, NOT actual game
    Bundle decoding or compatibility with future Unity versions.
    """
    import UnityPy
    import brotli
    import lz4.block
    from wlre.services.world.unity_textasset import extract_textasset
    from wlre.services.world.catalog_source_extractor import extract_catalog_source
    from wlre.services.world.eve_v115 import derive_eve_index
    from wlre.services.world.itemdata_v1 import parse_itemdata
    from wlre.services.world.catalog_adapters import parse_feature
    if not all(callable(x) for x in (UnityPy.load, extract_textasset,
                                     extract_catalog_source, derive_eve_index,
                                     parse_itemdata, parse_feature)):
        raise RuntimeError('UnityFS/TextAsset 解包器在打包後缺少必要入口')
    expected = b'LaLa native UnityFS codec check: offline only'
    lz4_packed = lz4.block.compress(expected)
    if lz4.block.decompress(lz4_packed) != expected:
        raise RuntimeError('Bundled LZ4 decoder failed')
    brotli_packed = brotli.compress(expected)
    if brotli.decompress(brotli_packed) != expected:
        raise RuntimeError('Bundled Brotli decoder failed')
    # Parse a tiny synthetic, empty UnityFS container through the real
    # UnityPy BundleFile reader. It has no game assets or user data.
    import struct
    header = b'UnityFS\x00' + struct.pack('>I', 6) + b'5.x.x\x00' + b'2019.4.0f1\x00'
    blocks = bytes(16) + struct.pack('>II', 0, 0)
    bundle = header + struct.pack('>QIII', len(header) + 20 + len(blocks),
                                  len(blocks), len(blocks), 0x40) + blocks
    environment = UnityPy.load(bundle)
    if environment.objects or environment.container:
        raise RuntimeError('Synthetic empty UnityFS decoded unexpected assets')
    print('UnityFS runtime self-test passed: UnityPy, empty UnityFS, LZ4, Brotli, adapters')
    return 0


def smoke_test_gui():
    """Exercise bundled Tcl/Tk and the dashboard without any game connection."""
    # GUI smoke tests must never initiate automatic official Bundle downloads.
    # This opt-out is scoped to the current smoke-test process only.
    os.environ["WLRE_DISABLE_AUTO_CATALOG"] = "1"
    self_test()
    import tkinter as tk
    from wlre.ui.application_host import DesktopHost
    root = tk.Tk()
    host = DesktopHost(root)
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    try:
        host.start()
        app = host.module.app
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
        host.finish()
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
        if '--self-test-unityfs' in sys.argv:return self_test_unityfs()
        if '--self-test' in sys.argv:return self_test()
        if os.name=='nt':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('WLRE.Client.ByChiNing')
        # Native EXE / macOS APP is its own launcher. Prepare verified
        # private candidates BEFORE importing Tk, never in login callbacks.
        from wlre.services.world.launcher_catalog import prepare_on_launch
        from wlre.launcher_progress import run_with_progress
        run_with_progress(prepare_on_launch)
        from wlre.ui.gui import main as run_gui
        run_gui()
        return 0
    except Exception:
        details=traceback.format_exc()
        with log.open('a',encoding='utf8') as stream:stream.write(details+'\n')
        if not any(flag in sys.argv for flag in ('--self-test','--smoke-test-gui','--self-test-unityfs')) and os.name=='nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,'程式啟動失敗，詳細記錄：\n'+str(log),'飄流Re:LaLa  =By赤寧=',0x10)
        elif sys.stderr:print(details,file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
