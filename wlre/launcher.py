"""Launch the desktop UI; create a private image environment only when needed."""
from pathlib import Path
import subprocess
import sys
import venv
from wlre.storage.atomic import file_lock


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
    # Launcher owns official Bundle preparation. The UI only reads the
    # resulting private, unapproved status; no download in Tk callbacks.
    # Dev launcher runs this in the same Python environment that launches Tk.
    # The compiled WLRE_Client entry runs the same service in-process.
    if '--navigation' not in sys.argv and '--self-test' not in sys.argv:
        try:
            subprocess.run([str(python), '-m',
                            'wlre.services.world.launcher_catalog'], cwd=root,
                           check=False)
        except OSError:
            # Startup remains possible for offline users; pre-login game
            # compatibility is independently enforced inside the client.
            print('Launcher 資源候選準備無法啟動，請檢查環境；登入限制維持。',
                  file=sys.stderr)
    return subprocess.run([str(python),*arguments],cwd=root).returncode


if __name__=='__main__':raise SystemExit(main())
