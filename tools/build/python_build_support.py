"""Locate development files for the selected interpreter, never another ABI."""
import json
from pathlib import Path
import shutil
import struct
import sys
import sysconfig


def development_files(prefixes=None, version=None, config=None):
    version = sys.version_info[:2] if version is None else version
    config = sysconfig.get_config_vars() if config is None else config
    if config.get('Py_GIL_DISABLED') or config.get('Py_DEBUG'):
        raise RuntimeError('請使用一般 64 位元 Python；目前不支援 free-threaded 或 debug Python 打包。')
    name = 'python%d%d.lib' % tuple(version)
    roots = [Path(p) for p in (prefixes if prefixes is not None else
             (sys.base_prefix, sys.base_exec_prefix, sys.prefix, sys.exec_prefix))]
    candidates = list(dict.fromkeys(root/'libs'/name for root in roots))
    library = next((p for p in candidates if p.is_file() and p.stat().st_size), None)
    header = next((root/'include'/'Python.h' for root in roots
                   if (root/'include'/'Python.h').is_file()), None)
    if library is None or header is None:
        raise RuntimeError(
            'Python 開發檔案不完整：需要 '+name+' 與 include/Python.h。\n'
            '檢查位置：\n'+'\n'.join(str(p) for p in candidates)+
            '\n請修復此 Python 安裝，包含 developer headers and libraries（Include_dev=1）及 Tcl/Tk，'
            '或安裝完整版 64 位元 Python 3.12 後重跑 BAT。不要使用其他版本的 .lib 改名替代。')
    return library, header


def stage_library(library, environment):
    """Expose the matching import library at the virtualenv's conventional path."""
    target = Path(environment)/'libs'/library.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if library.resolve() != target.resolve():
        shutil.copy2(library, target)
    return target


def main():
    try:
        if struct.calcsize('P') != 8 or not (3,10) <= sys.version_info[:2] <= (3,14):
            raise RuntimeError('需要 64 位元 Python 3.10～3.14。')
        import tkinter
        library, header = development_files()
        print(json.dumps({'python':sys.executable, 'library':str(library),
                          'header':str(header), 'tk':tkinter.TkVersion},ensure_ascii=False))
        return 0
    except (OSError, ImportError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
