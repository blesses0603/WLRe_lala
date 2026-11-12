"""Offline CI observations only; never opens application databases or changes policy."""
from contextlib import closing
import ctypes
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time


BUSY_SECONDS = 0.25
REPETITIONS = 3
WORKER_LIMIT_SECONDS = 20


def report(label, value):
    print(f'{label}: {json.dumps(value, ensure_ascii=True)}', flush=True)


def probe(directory):
    path = Path(directory) / 'busy-diagnostic.sqlite3'
    # Only the supervisor's fresh temporary directory is used. Refuse an
    # existing file even when somebody invokes the internal worker directly.
    with path.open('xb'):
        pass
    report('python', sys.version)
    report('platform', platform.platform())
    report('sqlite_version', sqlite3.sqlite_version)
    with closing(sqlite3.connect(path)) as blocker:
        report('sqlite_compile_options', [row[0] for row in blocker.execute('PRAGMA compile_options')])
        blocker.execute('CREATE TABLE diagnostic (value INTEGER)')
        blocker.commit()
        blocker.execute('BEGIN IMMEDIATE')
        try:
            for trial in range(REPETITIONS):
                with closing(sqlite3.connect(path, timeout=BUSY_SECONDS)) as contender:
                    configured_ms = contender.execute('PRAGMA busy_timeout').fetchone()[0]
                    start = time.monotonic()
                    try:
                        contender.execute('BEGIN IMMEDIATE')
                    except sqlite3.OperationalError as error:
                        elapsed = time.monotonic() - start
                        report('blocked_begin', dict(trial=trial + 1, configured_busy_ms=configured_ms,
                               elapsed_seconds=elapsed, sqlite_errorcode=getattr(error, 'sqlite_errorcode', None),
                               sqlite_errorname=getattr(error, 'sqlite_errorname', None),
                               in_transaction=contender.in_transaction))
                    else:
                        report('blocked_begin_unexpected_success', dict(trial=trial + 1,
                               elapsed_seconds=time.monotonic() - start))
                        contender.rollback()
        finally:
            blocker.rollback()
    # Resolve symbols through Python's already imported extension, not a guessed
    # system SQLite path. Missing exports are an observation, not a test failure.
    try:
        import _sqlite3
        library = ctypes.CDLL(_sqlite3.__file__)
        version = library.sqlite3_libversion
        version.argtypes = []
        version.restype = ctypes.c_char_p
        reported_version = version().decode('ascii')
        if reported_version != sqlite3.sqlite_version:
            report('sqlite_sleep_unavailable', 'extension symbol version differs from Python SQLite')
            return
        sleep = library.sqlite3_sleep
        sleep.argtypes = [ctypes.c_int]
        sleep.restype = ctypes.c_int
        for requested_ms in (1, 10, 250):
            start = time.monotonic()
            returned_ms = sleep(requested_ms)
            report('sqlite_sleep', dict(requested_ms=requested_ms, returned_ms=returned_ms,
                   elapsed_seconds=time.monotonic() - start))
    except (AttributeError, OSError, UnicodeError) as error:
        report('sqlite_sleep_unavailable', type(error).__name__)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        probe(sys.argv[2])
        return
    if len(sys.argv) != 1:
        raise SystemExit('Run without arguments; --worker is internal.')
    report('purpose', 'Observations only: SQLite busy sleep budget is not a wall-clock deadline; no timing assertions.')
    # The parent owns cleanup even when the worker times out or crashes. All
    # probes share one bounded child; no tests, policies or application imports.
    with tempfile.TemporaryDirectory(prefix='sqlite-busy-diagnostic-') as directory:
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', directory],
                                    timeout=WORKER_LIMIT_SECONDS, check=False)
            report('diagnostic_worker_exit', result.returncode)
        except subprocess.TimeoutExpired:
            report('diagnostic_worker_timeout_seconds', WORKER_LIMIT_SECONDS)
    # This is an observational step. Existing regression steps retain their
    # normal failure behavior regardless of unavailable diagnostic measurements.


if __name__ == '__main__':
    main()
