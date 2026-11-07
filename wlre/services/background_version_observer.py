"""Read-only version hints for the desktop, never a login/content gate.

Only three small official metadata endpoints and the active SQLite identity are
read. No manifest, Bundle, Runtime, derived table or persisted state is touched.
The EXE/DataVer pair follows the existing PC ResourcePath selection policy,
exactly like the foreground path; this is not a feed of all EXE releases.
Socket timeouts share an elapsed-time budget; late responses are discarded.
The caller owns its single background worker and publishes results on the UI
thread. Closing/superseding the schedule never cancels a live network syscall.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import threading
import time
from urllib.request import HTTPRedirectHandler, build_opener

from wlre.services import official_version
from wlre.services.official_resource_sync import observe_official_versions, validate_snapshot
from wlre.services.world.resource_database import read_active_database_identity
from wlre.storage.paths import data_root


DEFAULT_INTERVAL_SECONDS = 300
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 3600
FAILURE_BACKOFF_SECONDS = (60, 120, 300, 600)
_STATUSES = frozenset(('identifiers_match', 'identifiers_differ', 'unverified'))


@dataclass(frozen=True)
class VersionIdentifiers:
    data_ver: str
    exe_version: str
    data_package: str
    main_package: str


@dataclass(frozen=True)
class ObservationResult:
    """Identifiers for the existing parser's selected PC mapping, not all releases."""

    status: str
    reason: str
    official: VersionIdentifiers | None
    database: VersionIdentifiers | None
    checked_at_utc: str


def _snapshot_identifiers(snapshot):
    validate_snapshot(snapshot)
    return VersionIdentifiers(snapshot['data_ver'], snapshot['exe_version'],
                              snapshot['packages']['DataPackage'],
                              snapshot['packages']['MainPackage'])


def version_identifiers_from_database(identity):
    """Sanitize stored/full-gate identifiers without verifying resource bytes."""
    if (type(identity) is not dict or type(identity.get('schema_version')) is not int
            or identity['schema_version'] != 1 or type(identity.get('packages')) is not list
            or len(identity['packages']) != 2):
        return None
    packages = {}
    for entry in identity['packages']:
        if (type(entry) is not dict or entry.get('name') not in ('DataPackage', 'MainPackage')
                or entry['name'] in packages
                or type(entry.get('manifest_sha256')) is not str
                or not re.fullmatch('[0-9a-f]{64}', entry['manifest_sha256'])
                or type(entry.get('manifest_crc32_le')) is not str
                or not re.fullmatch('[0-9a-f]{8}', entry['manifest_crc32_le'])):
            return None
        packages[entry['name']] = entry.get('full_version')
    try:
        return _snapshot_identifiers({
            'schema_version': 1, 'origin': 'official_pc_version_endpoint',
            'data_ver': identity.get('data_ver'), 'exe_version': identity.get('exe_version'),
            'packages': packages, 'checked_at_utc': '', 'assets_ready': False,
        })
    except (ValueError, TypeError):
        return None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_metadata(url, *, timeout):
    """Reuse the official URL/TLS/body checks, without redirects or retries."""
    open_request = build_opener(_NoRedirect()).open
    attempted = False

    def open_once(request, **kwargs):
        nonlocal attempted
        if attempted:
            raise official_version.VersionSourceError('Background request already attempted')
        attempted = True
        return open_request(request, **kwargs)

    return official_version.fetch_bytes(url, timeout=timeout, opener=open_once,
                                        cache_bust=False)


def _finite_timeout(value, maximum):
    if isinstance(value, bool):
        raise ValueError('Invalid observation timeout')
    value = float(value)
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError('Invalid observation timeout')
    return value


def observe_background_versions(*, database_path=None, request_timeout=12.0,
                                timeout_budget=30.0, fetcher=None,
                                clock=time.monotonic):
    """Compare identifiers only; a match cannot approve login or packet sends.

    A fetcher takes ``(url, timeout=seconds)`` and returns bounded bytes. The
    production transport enforces official HTTPS, a 16 KiB response cap, and at
    most one GET per endpoint. The elapsed budget is checked before/after every
    operation; no result finishing outside it is presented as current. Socket
    timeout is not hard cancellation of OS DNS/SQLite calls.
    """
    request_timeout = _finite_timeout(request_timeout, 30.0)
    timeout_budget = _finite_timeout(timeout_budget, 30.0)
    deadline = clock() + timeout_budget
    official = None

    def result(status, reason, database=None):
        return ObservationResult(status, reason, official, database,
                                 datetime.now(timezone.utc).isoformat(timespec='seconds'))

    def remaining():
        value = deadline - clock()
        if value <= 0:
            raise TimeoutError('Observation elapsed budget exhausted')
        return value

    def fetch(url):
        timeout = min(request_timeout, remaining())
        body = (fetcher or _fetch_metadata)(url, timeout=timeout)
        remaining()
        if not isinstance(body, bytes) or len(body) > official_version.MAX_RESPONSE_BYTES:
            raise ValueError('Invalid metadata response')
        return body

    try:
        official = _snapshot_identifiers(observe_official_versions(fetcher=fetch))
        remaining()
    except Exception:
        return result('unverified', 'timeout' if clock() >= deadline else 'official_unavailable')
    try:
        path = (Path(database_path) if database_path is not None else
                data_root() / 'official_sync' / 'derived_catalogs' / 'resource_inventory.sqlite3')
        stored = read_active_database_identity(path)
        remaining()
        database = version_identifiers_from_database(stored)
        remaining()
    except Exception:
        return result('unverified', 'timeout' if clock() >= deadline else 'database_unavailable')
    if database is None:
        return result('unverified', 'database_unavailable')
    return result('identifiers_match' if official == database else 'identifiers_differ',
                  'observed', database)


def bounded_interval(value=DEFAULT_INTERVAL_SECONDS):
    try:
        parsed = float(value) if not isinstance(value, bool) else math.nan
    except (ValueError, TypeError, OverflowError):
        parsed = math.nan
    if not math.isfinite(parsed):
        return float(DEFAULT_INTERVAL_SECONDS)
    return max(float(MIN_INTERVAL_SECONDS), min(float(MAX_INTERVAL_SECONDS), parsed))


@dataclass(frozen=True)
class _ObservationToken:
    owner: object
    generation: int
    sequence: int


class ObservationSchedule:
    """Small, non-persistent, single-flight schedule with stale-result guards.

    ``begin`` reserves a worker slot, ``finish`` releases it. A manual forced
    begin skips the due time only, never single-flight or closure. Superseding
    keeps a live slot occupied until it actually finishes, but rejects its old
    result. There are no threads, timers, Tk references or full-gate retries.
    """

    def __init__(self, interval_seconds=DEFAULT_INTERVAL_SECONDS, *,
                 clock=time.monotonic, initial_delay=False):
        self.interval_seconds = bounded_interval(interval_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._owner = object()
        self._generation = 0
        self._sequence = 0
        self._in_flight = None
        self._closed = False
        self._next_due = clock() + (self.interval_seconds if initial_delay else 0)
        self.baseline = None
        self.latest = None
        self.changed_from_baseline = None
        self.last_success_at = None
        self.failure_count = 0

    def begin(self, *, force=False):
        with self._lock:
            if self._closed or self._in_flight is not None:
                return None
            if not force and self._clock() < self._next_due:
                return None
            self._sequence += 1
            self._in_flight = _ObservationToken(self._owner, self._generation, self._sequence)
            return self._in_flight

    def finish(self, token, result):
        with self._lock:
            if token is None or token != self._in_flight:
                return False
            self._in_flight = None
            if self._closed or token.generation != self._generation:
                return False
            valid = (isinstance(result, ObservationResult) and type(result.status) is str
                     and result.status in _STATUSES
                     and all(item is None or isinstance(item, VersionIdentifiers)
                             for item in (result.official, result.database)))
            if valid and result.status != 'unverified':
                valid = (result.official is not None and result.database is not None
                         and ((result.official == result.database) ==
                              (result.status == 'identifiers_match')))
            if not valid:
                result = ObservationResult('unverified', 'observation_unavailable', None, None,
                                           datetime.now(timezone.utc).isoformat(timespec='seconds'))
            self.latest = result
            self.changed_from_baseline = (None if self.baseline is None or result.official is None
                                          else self.baseline != result.official)
            if result.status == 'unverified':
                self.failure_count += 1
                delay = FAILURE_BACKOFF_SECONDS[min(self.failure_count - 1,
                                                    len(FAILURE_BACKOFF_SECONDS) - 1)]
            else:
                self.failure_count = 0
                self.last_success_at = result.checked_at_utc
                delay = self.interval_seconds
            self._next_due = self._clock() + delay
            return True

    def supersede(self, baseline=None):
        if baseline is not None and not isinstance(baseline, VersionIdentifiers):
            raise ValueError('Invalid version baseline')
        with self._lock:
            self._generation += 1
            self.baseline = baseline
            self.latest = None
            self.changed_from_baseline = None
            self.last_success_at = None
            self.failure_count = 0
            self._next_due = self._clock() + self.interval_seconds

    def close(self):
        with self._lock:
            self._closed = True
            self._generation += 1

    def set_interval(self, value):
        """Adjust the next normal poll without resetting results or live work."""
        with self._lock:
            self.interval_seconds = bounded_interval(value)
            # A settings edit cannot defeat failure backoff. An in-flight
            # result will schedule from its own completion using this value.
            if not self._closed and self.failure_count == 0:
                self._next_due = self._clock() + self.interval_seconds
            return self.interval_seconds

    def seconds_until_due(self):
        with self._lock:
            if self._closed or self._in_flight is not None:
                return None
            return max(0.0, self._next_due - self._clock())
