"""Launch the desktop UI; create a private image environment only when needed."""
from pathlib import Path
import subprocess
import sys
import venv


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
        if not python.exists():
            print('Preparing image support (first run)...',flush=True)
            venv.EnvBuilder(with_pip=True).create(environment)
        probe=subprocess.run([str(python),'-c',"from PIL import Image,ImageTk,features; assert hasattr(Image,'Resampling') and features.check('webp')"],
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if probe.returncode:
            subprocess.run([str(python),'-m','pip','install','-r',str(root/'requirements-ui.txt')],check=True)
    return subprocess.run([str(python),*arguments],cwd=root).returncode


if __name__=='__main__':raise SystemExit(main())
