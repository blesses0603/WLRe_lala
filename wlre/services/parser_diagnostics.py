"""Bounded, display-only diagnostics for official resource parsers.

No payloads, decoded strings, exception messages or filesystem paths are saved.
Observations and prior successful parses never authorize a runtime or a layout.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import tempfile

_run = ContextVar('resource_parser_run', default=None)
_cursor = ContextVar('resource_parser_cursor', default=None)
MAX_ENTRIES = 128
MAX_REPORT_BYTES = 256 * 1024
REGISTRY = {}


def checkpoint(*, offset=None, field=None, record=None, expected=None, actual=None,
               expected_max=None, constraint=None, profile=None):
    """Record code-owned field labels and numeric positions, never source text."""
    state = _cursor.get()
    if state is None:
        return
    for key, value in (('offset', offset), ('record', record),
                       ('expected', expected), ('actual', actual), ('expected_max', expected_max)):
        if type(value) is int and 0 <= value <= 2**63 - 1:
            state[key] = value
    if type(profile) is str and profile.isascii() and profile.replace('-', '').isalnum():
        state['profile'] = profile[:64]
    if type(field) is str and field.isascii() and field.replace('_', '').isalnum():
        state['field'] = field[:64]
    if type(constraint) is str and re.fullmatch(r'[a-z0-9_]{1,64}', constraint):
        state['constraint'] = constraint


def read_checkpoint(offset, size, available):
    state = _cursor.get()
    if state is not None:
        checkpoint(offset=offset)
        if type(size) is int and size >= 0:
            state['requested_bytes'] = size
        if type(available) is int and available >= 0:
            state['available_bytes'] = available


def _inputs(bound):
    return {name: {'size': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
            for name, value in bound.arguments.items() if type(value) is bytes}


def _baseline_key(event):
    return event['parser'] + ':' + event.get('variant', 'default')


def _valid_baseline(row):
    if type(row) is not dict or set(row) != {'schema', 'selected_schema', 'inputs', 'record_count', 'identity'}:
        return False
    if any(type(row[k]) is not str or not re.fullmatch(r'[a-zA-Z0-9.-]{1,80}', row[k])
           for k in ('schema', 'selected_schema')):
        return False
    if row['record_count'] is not None and (type(row['record_count']) is not int or not 0 <= row['record_count'] <= 2**31):
        return False
    if row['identity'] is not None and (type(row['identity']) is not str or not re.fullmatch(r'[0-9a-f]{64}', row['identity'])):
        return False
    inputs = row['inputs']
    return (type(inputs) is dict and len(inputs) <= 16 and all(
        type(k) is str and re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]{0,63}', k)
        and type(v) is dict and set(v) == {'size', 'sha256'}
        and type(v['size']) is int and 0 <= v['size'] <= 2**63 - 1
        and type(v['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', v['sha256'])
        for k, v in inputs.items()))


def _result_count(result):
    if type(result) is list:
        return len(result)
    if type(result) is tuple:
        return len(result[1]) if len(result) == 2 and type(result[1]) is list else None
    if type(result) is dict:
        for key in ('record_count', 'task_count', 'asset_count', 'scene_count'):
            if type(result.get(key)) is int:
                return result[key]
        for key in ('tasks', 'records'):
            if type(result.get(key)) in (dict, list):
                return len(result[key])
        return len(result)
    return None


def _location(error, state):
    # Some legacy parsers use struct offsets rather than a shared Reader.
    # Whitelist numeric cursors only. No locals or exception text is serialized.
    found = dict(state)
    tb = error.__traceback__
    while tb is not None:
        local = tb.tb_frame.f_locals
        for key in ('pos', 'offset'):
            value = local.get(key)
            if 'offset' not in found and type(value) is int and value >= 0:
                found['offset'] = value
        tb = tb.tb_next
    return found


def diagnosed(schema):
    """Keep the original result/exception type; annotate failures for callers."""
    def decorate(fn):
        parser_id = fn.__module__ + '.' + fn.__name__
        signature = inspect.signature(fn)
        REGISTRY[parser_id] = schema

        @wraps(fn)
        def wrapped(*args, **kwargs):
            run = _run.get()
            # Outside update sessions diagnostics are lazy: hash only on failure.
            bound = signature.bind(*args, **kwargs)
            parent = _cursor.get()
            state = {}
            token = _cursor.set(state)
            event = {'parser': parser_id, 'schema': schema}
            source = bound.arguments.get('source')
            if source in ('EventData.NewNpc', 'EventData.NewInteract'):
                event['variant'] = source
            binding = bound.arguments.get('binding')
            asset = getattr(binding, 'asset_path', '')
            if type(asset) is str:
                name = asset.rsplit('/', 1)[-1]
                if re.fullmatch(r'[a-zA-Z0-9_]{1,64}\.bytes', name):
                    event['variant'] = name
            try:
                result = fn(*args, **kwargs)
            except Exception as error:
                event.update(status='failed', inputs=_inputs(bound),
                             error_type=type(error).__name__,
                             location=_location(error, state))
                try:
                    error.parser_diagnostic = dict(event)
                except (AttributeError, TypeError):
                    pass
                if run is not None:
                    run.record(event)
                raise
            else:
                if run is not None and parent is None:
                    rejected = type(result) is dict and result.get('status') in ('layout_unrecognized', 'unsupported_table')
                    event.update(status='failed' if rejected else 'passed', inputs=_inputs(bound),
                                 record_count=_result_count(result),
                                 selected_schema=state.get('profile', schema))
                    if type(result) is bytes and not event['inputs']:
                        event['inputs'] = {'textasset': {'size': len(result), 'sha256': hashlib.sha256(result).hexdigest()}}
                    if fn.__name__ == 'parse_manifest' and type(result) is dict:
                        package = result.get('header', {}).get('package_name')
                        if package in ('MainPackage', 'DataPackage'):
                            event['variant'] = package
                    run.record(event)
                return result
            finally:
                _cursor.reset(token)
        wrapped.parser_schema = schema
        return wrapped
    return decorate


class DiagnosticRun:
    def __init__(self, root):
        self.root = Path(root) / 'parser_diagnostics'
        self.events = {}
        self.identities = []
        self.coverage = {}
        self.dropped_events = 0

    def record(self, event):
        # Keep distinct official inputs (e.g. the two Package manifests).
        key = (event['parser'], event.get('variant'), json.dumps(event.get('inputs', {}), sort_keys=True))
        previous = self.events.get(key)
        if previous is not None and previous['status'] == 'failed':
            return  # A later retry must not erase a failure in this run.
        self.events[key] = {**event, 'identity': self.identities[-1] if self.identities else None}
        while len(self.events) > MAX_ENTRIES:
            victim = next((k for k, v in self.events.items() if v['status'] != 'failed'),
                          next(iter(self.events)))
            del self.events[victim]
            self.dropped_events += 1

    def identity(self, identity):
        # identity is supplied by verified_manifest consumers, never a trust input.
        if type(identity) is str and len(identity) == 64 and all(c in '0123456789abcdef' for c in identity):
            if identity not in self.identities:
                self.identities.append(identity)

    def save(self):
        prior = _read(self.root / 'last_success.json')
        baseline = prior.get('parsers', {}) if type(prior) is dict else {}
        if type(baseline) is not dict:
            baseline = {}
        baseline = {k: v for k, v in baseline.items()
                    if type(k) is str and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,200}', k)
                    and _valid_baseline(v)}
        events = list(self.events.values())
        # Compare against the baseline that existed BEFORE this entire session.
        for event in events:
            old = baseline.get(_baseline_key(event))
            event['comparison'] = ('input_unavailable' if not event['inputs'] else
                'no_baseline' if old is None else
                'same_source' if old.get('inputs') == event.get('inputs') else 'source_changed')
            if old is not None:
                event['schema_changed'] = (event.get('selected_schema') is not None
                                          and old['selected_schema'] != event['selected_schema'])
                event['previous_success'] = {k: old.get(k) for k in
                    ('schema', 'selected_schema', 'inputs', 'record_count', 'identity')}
                if type(old.get('record_count')) is int and type(event.get('record_count')) is int:
                    event['record_count_delta'] = event['record_count'] - old['record_count']
                event['size_delta'] = {name: row['size'] - old['inputs'][name]['size']
                                       for name, row in event['inputs'].items()
                                       if name in old['inputs']}
        for event in events:
            if event['status'] == 'passed' and event['inputs']:
                baseline[_baseline_key(event)] = {k: event.get(k) for k in
                    ('schema', 'selected_schema', 'inputs', 'record_count', 'identity')}
        report = {'schema_version': 1,
                  'checked_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                  'identities': self.identities[-8:], 'parsers': events,
                  'coverage': self.coverage,
                  'dropped_events': self.dropped_events,
                  'assets_ready': False, 'can_send_packets': False}
        self.root.mkdir(parents=True, exist_ok=True)
        _write(self.root / 'latest.json', report)
        _write(self.root / 'last_success.json', {'parsers': dict(list(baseline.items())[-MAX_ENTRIES:])})


def _read(path):
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_REPORT_BYTES + 1)
        return json.loads(raw) if len(raw) <= MAX_REPORT_BYTES else None
    except (OSError, ValueError):
        return None


def _write(path, report):
    raw = json.dumps(report, ensure_ascii=True, sort_keys=True).encode('utf-8')
    if len(raw) > MAX_REPORT_BYTES:
        return
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.parser_', delete=False) as stream:
            pending = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def diagnostics_active():
    return _run.get() is not None


def record_coverage(coverage):
    if _run.get() is not None:
        current = _run.get().coverage
        for key, value in coverage.items():
            if current.get(key) == 'failed' or (value == 'not_available' and key in current):
                continue
            current[key] = value


def record_identity(identity):
    if _run.get() is not None:
        _run.get().identity(identity)


@contextmanager
def diagnostic_session(root):
    """Nested update paths share one report, including swallowed parser failures."""
    if _run.get() is not None:
        yield _run.get()
        return
    run = DiagnosticRun(root)
    token = _run.set(run)
    try:
        yield run
    finally:
        _run.reset(token)
        try:
            run.save()
        except (OSError, ValueError, TypeError):
            pass  # Optional reporting cannot change parsing or login decisions.


def update_diagnostics(root_parameter, injected=()):
    """Persist real updates; fixtures opt in using diagnostic_session explicitly."""
    def decorate(fn):
        signature = inspect.signature(fn)
        @wraps(fn)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            root = bound.arguments.get(root_parameter)
            if any(bound.arguments.get(k) is not None for k in injected):
                return fn(*args, **kwargs)
            if bound.arguments.get('download') is False:
                return fn(*args, **kwargs)
            env = bound.arguments.get('environ')
            if fn.__name__ == 'prepare_on_launch' and (os.environ if env is None else env).get('WLRE_DISABLE_AUTO_CATALOG') == '1':
                return fn(*args, **kwargs)
            if root is None:
                from wlre.storage.paths import data_root
                root = data_root() / 'official_sync'
            with diagnostic_session(root):
                return fn(*args, **kwargs)
        return wrapped
    return decorate
