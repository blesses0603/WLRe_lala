"""Windows Nuitka build coordinator; testable planning requires no compiler."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import shutil
import subprocess
import sys
import venv
from wlre import __version__
from tools.build.python_build_support import development_files, stage_library

ROOT=Path(__file__).resolve().parents[2]
DATA_SUFFIXES={'.json','.zip','.png','.ico'}


def data_files(root=ROOT):
    return sorted(p for p in (root/'wlre').rglob('*')
                  if p.is_file() and p.suffix.lower() in DATA_SUFFIXES
                  and not any(part.startswith('.') or part=='__pycache__' for part in p.relative_to(root).parts))


def make_command(python,mode='standalone',root=ROOT,compiler='auto',diagnose_compiler=False):
    output=root/'dist_nuitka'/mode
    command=[str(python),'-m','nuitka','--mode='+mode,'--enable-plugin=tk-inter',
             '--include-package=wlre','--windows-console-mode=disable',
             '--windows-icon-from-ico='+str(root/'wlre/resources/assets/app.ico'),
             '--output-filename=WLRE_Client.exe','--output-dir='+str(output),
             '--report='+str(output/'compilation-report.xml'),'--assume-yes-for-downloads',
             '--jobs='+str(max(1,min(4,os.cpu_count() or 1))),
             '--company-name=ByChiNing','--product-name=飄流Re:LaLa  =By赤寧=',
             '--file-description=飄流Re:LaLa  =By赤寧=',
             '--file-version='+__version__+'.0','--product-version='+__version__+'.0']
    if compiler!='auto':command.append('--msvc=latest' if compiler=='msvc' else '--mingw64')
    if diagnose_compiler:
        # --show-scons enables SCons --debug=stacktrace in Nuitka 4.3.
        # Bypass clcache only on this diagnostic run, leaving defaults intact.
        command.extend(['--disable-cache=ccache', '--show-scons'])
    command.extend('--include-data-files='+str(p)+'='+p.relative_to(root).as_posix() for p in data_files(root))
    command.append(str(root/'WLRE_Client.py'))
    return command


def build_environment(environ=None, library_dir=None):
    env=dict(os.environ if environ is None else environ)
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    if library_dir is not None:
        env['LIB']=str(library_dir)+(os.pathsep+env['LIB'] if env.get('LIB') else '')
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1')
    return env


def run_logged(command,log,library_dir=None):
    env=build_environment(library_dir=library_dir)
    with log.open('a',encoding='utf8') as stream:
        stream.write('\n'+subprocess.list2cmdline(command)+'\n');stream.flush()
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace')
        try:
            for line in process.stdout:
                print(line,end='',flush=True);stream.write(line);stream.flush()
            code=process.wait()
        except BaseException:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            raise
        if code:raise RuntimeError(f'指令執行失敗（結束碼 {code}）；請查看 '+str(log))


def select_compiler(requested='auto',version=None,msvc_available=None):
    version=sys.version_info[:2] if version is None else version
    if msvc_available is None:
        msvc_available=bool(shutil.which('cl'))
        vswhere=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
        if not msvc_available and vswhere.is_file():
            result=subprocess.run([str(vswhere),'-latest','-version','[17.0,)','-products','*','-requires',
                'Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],
                capture_output=True,text=True,encoding='utf8',errors='replace',check=False)
            msvc_available=result.returncode==0 and bool(result.stdout.strip())
    if requested=='mingw64' and version>=(3,13):
        raise RuntimeError('Python 3.13／3.14 不使用 MinGW64；請改用 --compiler msvc，或以 Python 3.12 打包。')
    if requested=='msvc' or version>=(3,13):
        if not msvc_available:
            raise RuntimeError(
                '已偵測 Python '+'.'.join(map(str,version))+'，但未找到 MSVC C++ 編譯工具。\n'
                '請安裝 Visual Studio 2022 Build Tools，勾選「使用 C++ 的桌面開發」、MSVC 及 Windows SDK：\n'
                'https://visualstudio.microsoft.com/visual-cpp-build-tools/\n'
                '或安裝 64 位元 Python 3.12（含 Tcl/Tk），重開 BAT 後會優先使用它，並由 Nuitka 下載 MinGW64。')
        return 'msvc'
    if requested=='mingw64':return 'mingw64'
    return 'msvc' if msvc_available else 'mingw64'


def prepare_environment(environment, log):
    """Repair only the disposable build venv, using the base Python's ensurepip."""
    python = environment / 'Scripts/python.exe'
    probe = [str(python), '-m', 'pip', '--version']
    if python.exists():
        try:
            run_logged(probe, log)
            return python
        except (OSError, RuntimeError):
            message = '打包環境的 Python／pip 無法啟動，重新建立專用環境：' + str(environment)
            print(message, flush=True)
            with log.open('a', encoding='utf8') as stream:
                stream.write('\n' + message + '\n')
            # Reinstalling pip with the broken pip cannot repair its imports.
            # clear=True also removes stale dependencies and their cache marker.
            venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    else:
        venv.EnvBuilder(with_pip=True).create(environment)
    # One repair attempt only. Do not proceed to downloads or compilation if
    # the bundled pip still fails (for example, a broken base installation).
    try:
        run_logged(probe, log)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError('重建打包環境後 pip 仍無法啟動；請查看 build.log，並修復基礎 Python 安裝（含 pip／venv），再重試。') from exc
    return python


def prepare_dependencies(python,environment,log,upgrade=False):
    """Reuse validated build dependencies; retry whenever validation fails."""
    requirements=ROOT/'requirements-build.txt'
    signature=hashlib.sha256(requirements.read_bytes()+b'\0'+(ROOT/'requirements-ui.txt').read_bytes()).hexdigest()
    marker=environment/'dependencies.sha256'
    try:cached=marker.read_text(encoding='ascii')==signature
    except OSError:cached=False
    probe=[str(python),'-c',"import tkinter; from PIL import Image,ImageTk,features; assert features.check('webp'); import nuitka"]
    if cached and not upgrade:
        try:
            run_logged([str(python),'-m','pip','check'],log)
            run_logged(probe,log)
            return
        except RuntimeError:pass
    marker.unlink(missing_ok=True)
    if upgrade:run_logged([str(python),'-m','pip','install','--upgrade','pip'],log)
    run_logged([str(python),'-m','pip','install','--upgrade','-r',str(requirements)],log)
    run_logged([str(python),'-m','pip','check'],log)
    run_logged(probe,log)
    marker.write_text(signature,encoding='ascii')


def main(argv=None):
    parser=argparse.ArgumentParser(description='Nuitka Windows 打包')
    parser.add_argument('--mode',choices=('standalone','onefile'),default='standalone')
    parser.add_argument('--compiler',choices=('auto','msvc','mingw64'),default='auto')
    parser.add_argument('--dry-run',action='store_true',help='只檢查並列出打包計畫，不安裝或編譯')
    parser.add_argument('--upgrade-deps',action='store_true',help='重新更新打包依賴與 pip')
    parser.add_argument('--diagnose-compiler',action='store_true',
                        help='本次停用 C 編譯快取並記錄 SCons 詳細指令及錯誤堆疊')
    args=parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps({'version':__version__,'command':make_command(sys.executable,args.mode,compiler=args.compiler,diagnose_compiler=args.diagnose_compiler),
                          'resource_count':len(data_files())},ensure_ascii=False,indent=2));return 0
    if os.name!='nt':parser.error('Windows EXE 請在 Windows 執行 build_nuitka.bat')
    if not (3,10)<=sys.version_info[:2]<=(3,14) or struct.calcsize('P')!=8:
        parser.error('請安裝 64 位元 Python 3.10～3.14，建議 3.12（含 Tcl/Tk）')
    output=ROOT/'dist_nuitka'/args.mode;output.mkdir(parents=True,exist_ok=True)
    log=output/'build.log';log.write_text('WLRE '+__version__+' Nuitka build\n',encoding='utf8')
    try:
        library,header=development_files()
        compiler=select_compiler(args.compiler)
        print('使用 Python '+sys.version.split()[0]+'（64 位元）／'+compiler,flush=True)
        with log.open('a',encoding='utf8') as stream:stream.write('Python: '+sys.version+'\nExecutable: '+sys.executable+'\nCompiler: '+compiler+'\n')
        environment=ROOT/'.nuitka-env'/('py'+'.'.join(map(str,sys.version_info[:2])))
        python=prepare_environment(environment,log)
        staged=stage_library(library,environment)
        print('Python import library: '+str(library),flush=True)
        with log.open('a',encoding='utf8') as stream:
            stream.write('Import library: '+str(library)+'\nStaged library: '+str(staged)+'\nHeader: '+str(header)+'\n')
        prepare_dependencies(python,environment,log,args.upgrade_deps)
        if args.diagnose_compiler:
            print('編譯診斷模式：本次停用 C 編譯快取，啟用 SCons 詳細指令與錯誤堆疊。',flush=True)
        run_logged(make_command(python,args.mode,compiler=compiler,
                                diagnose_compiler=args.diagnose_compiler),log,library_dir=staged.parent)
        executable=(output/'WLRE_Client.exe') if args.mode=='onefile' else (output/'WLRE_Client.dist/WLRE_Client.exe')
        if not executable.is_file():raise RuntimeError('編譯未產生預期的 EXE：'+str(executable))
        run_logged([str(executable),'--self-test'],log)
        print('\n打包及資源自檢完成：'+str(executable),flush=True)
        if args.mode=='standalone':print('分享時請複製整個 WLRE_Client.dist 資料夾。',flush=True)
        return 0
    except (OSError,RuntimeError,subprocess.SubprocessError) as exc:
        with log.open('a',encoding='utf8') as stream:stream.write('\nERROR: '+str(exc)+'\n')
        print('\n打包失敗：'+str(exc)+'\n記錄：'+str(log),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
