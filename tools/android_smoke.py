"""No-account emulator smoke test: UI, service, Home and screen-off survival."""
import subprocess
import sys
import time
from pathlib import Path

PACKAGE = 'org.lala.client.wlrelala'


def adb(*args, check=True):
    return subprocess.run(['adb', *args], text=True, capture_output=True, check=check).stdout


def alive(name):
    return bool(adb('shell', 'pidof', name, check=False).strip())


def main():
    apk = next(Path('bin').glob('*.apk'))
    subprocess.run(['adb', 'install', '-r', '-g', str(apk)], check=True)
    adb('logcat', '-c')
    adb('shell', 'am', 'start', '-W', '-n', PACKAGE + '/org.kivy.android.PythonActivity')
    try:
        deadline = time.monotonic() + 90
        while True:
            logs = adb('logcat', '-d', '-v', 'threadtime')
            if 'WLRE_ANDROID_UI_READY' in logs and 'WLRE_ANDROID_SERVICE_CONNECTED' in logs: break
            if time.monotonic() >= deadline: raise RuntimeError('UI/service readiness markers missing')
            time.sleep(2)
        assert alive(PACKAGE), 'Activity process exited'
        service = PACKAGE + ':service_Connections'
        assert alive(service), 'Foreground service process exited'
        adb('shell', 'input', 'keyevent', '3')  # Home, keep task intact.
        time.sleep(15)
        assert alive(service), 'Service exited after Home'
        adb('shell', 'input', 'keyevent', '223')  # Sleep.
        time.sleep(30)
        assert alive(service), 'Service exited while screen off'
        adb('shell', 'input', 'keyevent', '224')
        adb('shell', 'wm', 'dismiss-keyguard')
        adb('shell', 'am', 'start', '-W', '-n', PACKAGE + '/org.kivy.android.PythonActivity')
        time.sleep(5)
        assert alive(PACKAGE), 'Activity exited after resume'
        assert alive(service), 'Service exited after resume'
        print('Android UI + foreground service + Home + 30-second screen-off smoke passed (no accounts/network login)')
    finally:
        logs = adb('logcat', '-d', '-v', 'threadtime')
        Path('android-smoke-logcat.txt').write_text(logs)
        if sys.exc_info()[0] is not None:
            relevant = [line for line in logs.splitlines() if any(
                marker in line.lower() for marker in ('python', 'androidruntime', 'linker', 'wlre', 'libc'))]
            print('\n'.join(relevant[-500:]), flush=True)
        Path('android-smoke-services.txt').write_text(adb('shell', 'dumpsys', 'activity', 'services', PACKAGE))


if __name__ == '__main__': main()
