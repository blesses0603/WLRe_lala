"""Keep GUI regressions offline and destroy Tcl-owned cycles on their UI thread."""
import gc
import threading
from unittest.mock import patch


def isolate_gui_background_checks(case):
    """GUI fixtures test presentation; version/resource services have own tests.

    Live network workers can outlive a destroyed test root. Heavy decoding in
    a later worker may then collect that root's Tcl objects on the wrong thread.
    Stub only the external checks, preserve the GUI queue/generation machinery,
    and release destroyed fixture graphs on the creating thread.
    """
    ui_thread = threading.get_ident()

    def release():
        if threading.get_ident() != ui_thread:
            raise RuntimeError('GUI fixtures must be released on their Tk thread')
        for worker in threading.enumerate():
            if worker.name in ('official-version-check', 'lala-release-check'):
                worker.join(timeout=1)
        for key in list(vars(case)):
            if not key.startswith('_'):
                setattr(case, key, None)
        gc.collect()

    official = patch('wlre.ui.version_gate_controller.run_prelogin_check',
        return_value={'status': 'unverified', 'blocked': True,
                      'message': '離線 GUI 測試，尚未驗證官方版本',
                      'remote': {'status': 'unverified', 'packages': {}}})
    release_check = patch('wlre.ui.version_gate_controller.check_lala_release',
                          side_effect=OSError('offline GUI fixture'))
    official.start()
    release_check.start()
    case.addCleanup(official.stop)
    case.addCleanup(release_check.stop)
    # Join workers while their offline patches are still active.
    case.addCleanup(release)
