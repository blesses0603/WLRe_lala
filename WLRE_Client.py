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
    from Crypto.Cipher import AES
    if AES.new(bytes(16),AES.MODE_CBC,bytes(16)).encrypt(bytes(16)).hex()!='66e94bd4ef8a2c3b884cfa59ca342b2e':
        raise RuntimeError('Bundled official Lua AES codec failed its known-answer check')
    import brotli
    import lz4.block
    from UnityPy.classes import TextAsset
    from UnityPy.classes.ClassIDTypeToClassMap import ClassIDTypeToClassMap
    from UnityPy.enums import ClassIDType
    from wlre.services.world.unity_textasset import extract_textasset
    from wlre.services.world.catalog_source_extractor import extract_catalog_source
    from wlre.services.world.eve_v115 import derive_eve_index
    from wlre.services.world.itemdata_v1 import parse_itemdata
    from wlre.services.world.catalog_adapters import parse_feature
    if not all(callable(x) for x in (UnityPy.load, extract_textasset,
                                     extract_catalog_source, derive_eve_index,
                                     parse_itemdata, parse_feature)):
        raise RuntimeError('UnityFS/TextAsset 解包器在打包後缺少必要入口')
    # Exercise the generated table too: an empty Bundle never instantiates
    # asset classes, so merely importing UnityPy could miss a packaging defect.
    asset = TextAsset(m_Name='LaLa offline fixture', m_Script='bundled class check')
    if (asset.m_Name != 'LaLa offline fixture'
            or asset.m_Script != 'bundled class check'
            or ClassIDTypeToClassMap[ClassIDType.TextAsset] is not TextAsset):
        raise RuntimeError('Bundled UnityPy generated TextAsset class failed')
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
    from wlre.ui.gui import App
    from wlre.ui.window_layout import wait_for_widget_mapping
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    try:
        app = App(root)
        app.show_main()
        # Windows needs native Map/Configure events after deiconify, whereas
        # an unbounded full update can stall on unattended Cocoa runners.
        # Wait for the actual dashboard without running startup/network timers.
        wait_for_widget_mapping(app.overview_panel)
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
    return 0


def main():
    from wlre.storage.paths import error_log_file
    log=error_log_file()
    # Logging is best-effort: a read-only data directory must not prevent
    # startup or replace the original failure with a diagnostic-write error.
    try:
        log.parent.mkdir(parents=True,exist_ok=True)
        # Console-less EXEs still keep Tk callback errors when writable.
        if sys.stderr is None:sys.stderr=log.open('a',encoding='utf8',buffering=1)
    except OSError:
        pass
    try:
        if '--smoke-test-gui' in sys.argv:return smoke_test_gui()
        if '--self-test-unityfs' in sys.argv:return self_test_unityfs()
        if '--self-test' in sys.argv:return self_test()
        if os.name=='nt':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('WLRE.Client.ByChiNing')
        # Native and direct/source GUI entry points share App's single startup
        # window. Resource preparation never replaces official login checks.
        from wlre.ui.gui import main as run_gui
        run_gui()
        return 0
    except Exception:
        details=traceback.format_exc()
        logged=False
        try:
            with log.open('a',encoding='utf8') as stream:stream.write(details+'\n')
            logged=True
        except OSError:
            pass
        try:
            if not any(flag in sys.argv for flag in ('--self-test','--smoke-test-gui','--self-test-unityfs')) and os.name=='nt':
                import ctypes
                message=('程式啟動失敗，詳細記錄：\n'+str(log) if logged else
                         '程式啟動失敗，無法寫入錯誤記錄：\n'+details)
                ctypes.windll.user32.MessageBoxW(None,message,'飄流Re:LaLa  =By赤寧=',0x10)
            elif sys.stderr:print(details,file=sys.stderr)
        except Exception:
            # An unavailable console/dialog must not mask the startup error.
            pass
        return 1


if __name__=='__main__':raise SystemExit(main())
