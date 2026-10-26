"""Launch the desktop UI; create a private image environment only when needed."""
from pathlib import Path
import subprocess
import sys
import venv
from wlre.storage.atomic import file_lock


def ensure_extractor_environment(python, root):
    """Use a private venv if the source-code launcher lacks the pinned UnityPy.

    Never install dependencies to the system interpreter just to run LaLa.
    Native Nuitka bundles already include UnityPy and do not use this path.
    """
    if '--navigation' in sys.argv or '--self-test' in sys.argv:
        return python
    requirement = root / 'requirements-extractor.txt'
    pinned = next((line.split('==', 1)[1].strip()
                   for line in requirement.read_text(encoding='utf-8').splitlines()
                   if line.startswith('UnityPy==')), None)
    if not pinned:
        raise RuntimeError('LaLa 缺少已審核的 UnityPy 固定版本')
    check = ("import importlib.metadata as m; import UnityPy, lz4.block, brotli; "
             "from PIL import Image, ImageTk, features; "
             "assert m.version('UnityPy') == " + repr(pinned) + "; "
             "assert features.check('webp') and callable(UnityPy.load)")
    def valid(executable):
        try:
            return subprocess.run([str(executable), '-c', check],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0
        except OSError:
            return False

    if valid(python):
        return python
    environment = root / '.ui-env'
    private = environment / ('Scripts/python.exe' if sys.platform == 'win32'
                             else 'bin/python')
    try:
        with file_lock(environment, timeout=300):
            if not private.exists():
                print('LaLa Launcher：準備私人 Python 解包環境…', flush=True)
                venv.EnvBuilder(with_pip=True).create(environment)
            if not valid(private):
                subprocess.run([str(private), '-m', 'pip', 'install',
                                '-r', str(root / 'requirements-ui.txt'),
                                '-r', str(requirement)], check=True)
                if not valid(private):
                    raise RuntimeError('LaLa 私有環境 UnityPy 驗證失敗')
        return private
    except (OSError, subprocess.CalledProcessError, RuntimeError):
        # Do not rewrite the official login decision merely because this
        # development-only dependency installation failed.
        print('Launcher 解包依賴尚未就緒，登入限制仍依官方驗證結果。',
              file=sys.stderr)
        return python


def main():
    root=Path(__file__).resolve().parents[1]
    arguments=['-m','wlre.ui.navigation_gui'] if '--navigation' in sys.argv else ['-m','wlre.ui.gui']
    python=Path(sys.executable)
    try:
        from PIL import Image,features
        from PIL import ImageTk  # noqa: F401 -- verify Tk image support before launch
        assert hasattr(Image,'Resampling') and features.check('webp')
    except (ImportError,AssertionError):
        environment=root/'.ui-env'
        python=environment/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
        # A second client must wait until the first finishes creating/installing.
        with file_lock(environment,timeout=300):
            if not python.exists():
                print('Preparing image support (first run)...',flush=True)
                venv.EnvBuilder(with_pip=True).create(environment)
            probe=subprocess.run([str(python),'-c',"from PIL import Image,ImageTk,features; assert hasattr(Image,'Resampling') and features.check('webp')"],
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if probe.returncode:
                subprocess.run([str(python),'-m','pip','install','-r',str(root/'requirements-ui.txt')],check=True)
                subprocess.run([str(python),'-c',"from PIL import Image,ImageTk,features; assert hasattr(Image,'Resampling') and features.check('webp')"],check=True)
    # Launcher owns official Bundle preparation before UI. Python users
    # also get the pinned decoder in a private venv, with no system pip edits.
    if '--navigation' not in sys.argv and '--self-test' not in sys.argv:
        python = ensure_extractor_environment(python, root)
        try:
            subprocess.run([str(python), '-m',
                            'wlre.services.world.launcher_catalog', '--progress'], cwd=root,
                           check=False)
        except OSError:
            print('Launcher 資源候選準備無法啟動；登入限制維持。',
                  file=sys.stderr)
    return subprocess.run([str(python),*arguments],cwd=root).returncode


if __name__=='__main__':raise SystemExit(main())
