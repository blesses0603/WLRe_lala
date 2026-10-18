"""Native macOS Nuitka app bundle build; planning also works on other hosts."""
import argparse
import json
import os
import platform
from pathlib import Path
import plistlib
import subprocess
import sys

from wlre import __version__
from tools.build.build_nuitka import ROOT, compiler_jobs, data_files, run_logged


def native_arch(machine=None):
    machine = platform.machine() if machine is None else machine
    try:
        return {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64', 'AMD64': 'x64'}[machine]
    except KeyError:
        raise ValueError('不支援的 macOS 架構：' + machine) from None


def output_dir(root=ROOT, arch=None):
    return root / 'dist_nuitka' / ('macos_' + (arch or native_arch()))


def make_command(python, root=ROOT, arch=None, jobs=None):
    arch = arch or native_arch()
    if arch not in ('arm64', 'x64'):
        raise ValueError('macOS 架構必須為 arm64 或 x64')
    output = output_dir(root, arch)
    command = [str(python), '-m', 'nuitka', 
        '--macos-create-app-bundle', '--macos-app-name=WLRe_LaLa',
        '--macos-signed-app-name=com.bychining.wlre-lala',
        '--macos-app-version=' + __version__,
        '--macos-app-mode=gui',
        '--macos-app-icon=' + str(root / 'wlre/resources/assets/app.ico'),
        '--macos-target-arch=' + ('x86_64' if arch == 'x64' else 'arm64'),
        '--enable-plugin=tk-inter', '--include-package=wlre',
        '--output-folder-name=WLRe_LaLa', '--output-filename=WLRe_LaLa', '--output-dir=' + str(output),
        '--report=' + str(output / 'compilation-report.xml'),
        '--assume-yes-for-downloads',
        '--jobs=' + str(compiler_jobs(jobs))]
    command.extend('--include-data-files=' + str(p) + '=' + p.relative_to(root).as_posix()
                   for p in data_files(root))
    command.append(str(root / 'WLRE_Client.py'))
    return command


def bundle_executable(bundle):
    """Read the actual entry name instead of assuming Nuitka's plist layout."""
    with (bundle / 'Contents/Info.plist').open('rb') as stream:
        name = plistlib.load(stream).get('CFBundleExecutable')
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError('App bundle 的 CFBundleExecutable 無效')
    executable = bundle / 'Contents/MacOS' / name
    if not executable.is_file() or not executable.stat().st_size or not os.access(executable, os.X_OK):
        raise ValueError('App bundle 缺少可執行的主程式：' + str(executable))
    return executable


def verify_binary_arch(executable, arch):
    """Reject an APP whose Mach-O entry cannot run on the requested runner."""
    expected = {'arm64': 'arm64', 'x64': 'x86_64'}[arch]
    result = subprocess.run(['lipo', '-archs', str(executable)],
                            capture_output=True, text=True, check=True)
    available = result.stdout.strip().split()
    if expected not in available:
        raise ValueError(f'App 主程式架構不符：需要 {expected}，實際為 {available}')
    return available


def main(argv=None):
    parser = argparse.ArgumentParser(description='macOS Nuitka .app 打包（需在 macOS 執行）')
    parser.add_argument('--arch', choices=('arm64', 'x64'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--jobs', type=int, help='C 編譯並行工作數（1～16）；預設最多 6')
    args = parser.parse_args(argv)
    try:
        compiler_jobs(args.jobs)
    except ValueError as exc:
        parser.error(str(exc))
    arch = args.arch or native_arch()
    if args.dry_run:
        print(json.dumps({'version': __version__, 'arch': arch,
                          'command': make_command(sys.executable, arch=arch, jobs=args.jobs)}, ensure_ascii=False, indent=2))
        return 0
    if sys.platform != 'darwin':
        parser.error('macOS .app 必須在 macOS 原生編譯')
    if arch != native_arch():
        parser.error('請在對應架構的 macOS runner 執行，不進行跨架構編譯')
    output = output_dir(arch=arch)
    output.mkdir(parents=True, exist_ok=True)
    log = output / 'build.log'
    log.write_text(f'WLRE {__version__} macOS {arch} Nuitka build\nPython: {sys.version}\n', encoding='utf8')
    try:
        # The workflow installs requirements into its isolated setup-python.
        run_logged([sys.executable, '-m', 'pip', 'check'], log)
        run_logged([sys.executable, '-c', 'import tkinter; from PIL import Image,ImageTk; import nuitka; print(tkinter.TkVersion)'], log)
        run_logged(make_command(sys.executable, arch=arch, jobs=args.jobs), log)
        bundle = output / 'WLRe_LaLa.app'
        executable = bundle_executable(bundle)
        verify_binary_arch(executable, arch)
        run_logged([str(executable), '--self-test'], log)
        # GitHub's macos-15-intel hosted runner can have no usable WindowServer:
        # its Tk event loop hangs despite the compiled executable launching.
        # Skip *only* the visual smoke test when CI explicitly sets this.
        # The bundled executable must still pass its full --self-test.
        if os.environ.get('WLRE_NATIVE_GUI_SMOKE', '1') == '0':
            print('WARN: Intel CI runner has no usable GUI; native APP GUI smoke requires manual Mac verification.', flush=True)
            with log.open('a', encoding='utf8') as stream:
                stream.write('GUI SMOKE NOT VERIFIED: hosted runner has no usable WindowServer\n')
        else:
            run_logged([str(executable), '--smoke-test-gui'], log)
        run_logged(['codesign', '--verify', '--deep', '--strict', str(bundle)], log)
        print('打包、資源及 GUI 自檢完成：' + str(bundle), flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        with log.open('a', encoding='utf8') as stream:
            stream.write('\nERROR: ' + str(exc) + '\n')
        print(str(exc) + '\n記錄：' + str(log), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
