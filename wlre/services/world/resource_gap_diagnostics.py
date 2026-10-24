"""Read-only inventory of the exact sources required by the pinned 1275 runtime.

Detect a missing archive, missing member, corrupt member, and source-schema
failure without treating candidate hashes as approval. No downloads, writes
to game files, login permissions, or private absolute paths in the report.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile, BadZipFile

from wlre.storage.paths import data_root
from wlre.services.world.game_data_1275 import read_manifest, verify_archive
from wlre.services.world.npc_1275_eve import FILES as EVE_FILES, read_verified_zip

SCHEMA = 1
FILENAME = 'resource_gap_report.json'
MAX_REPORT_BYTES = 12288
MAX_DETAIL = 20
ARCHIVES = ('1275_DataCatalog.zip', '1275_EveNpcIndex.zip')
STATES = ('missing', 'verified', 'invalid')
REQUIRED_GROUPS = {
    ARCHIVES[0]: ('160 張原始資料表', 'TalkData_C', 'TextData_C', 'ItemData_C'),
    ARCHIVES[1]: ('NPC 事件索引', 'NPC 互動選單索引'),
}


def _zip_members(archive, expected):
    names = [entry.filename for entry in archive.infolist()]
    known = set(expected)
    missing = sorted(known - set(names))
    unexpected = sorted(set(names) - known)
    duplicates = len(names) != len(set(names))
    return missing, unexpected, duplicates


def _inspect_archive(path, name):
    state = {'state': 'missing', 'missing': [], 'invalid': [],
             'verified_entries': 0, 'required_entries': (
                 163 if name == ARCHIVES[0] else 2)}
    if not path.is_file() or path.is_symlink():
        return state
    state['state'] = 'invalid'
    try:
        with ZipFile(path) as z:
            if name == ARCHIVES[0]:
                # The pinned manifest cannot be forged locally to redefine
                # what is considered a required 1275 table.
                manifest = read_manifest(z)
                expected = set(manifest['files']) | {'manifest.json', '使用說明.txt'}
                missing, unexpected, duplicate = _zip_members(z, expected)
                state['missing'] = missing[:MAX_DETAIL]
                if len(missing) > MAX_DETAIL:
                    state['missing'].append(f'其他 {len(missing) - MAX_DETAIL} 個缺項')
                state['invalid'] = unexpected[:MAX_DETAIL]
                if duplicate:
                    state['invalid'].append('ZIP 包含重複檔名')
                if not missing and not unexpected and not duplicate:
                    # Pin all 163 SHA-256 checks; even matching ZIP entries
                    # cannot prove schema compatibility without the loader.
                    verify_archive(path)
                    state['state'] = 'verified'
                    state['verified_entries'] = 163
            else:
                expected = set(EVE_FILES) | {'README.txt'}
                missing, unexpected, duplicate = _zip_members(z, expected)
                state['missing'] = missing[:MAX_DETAIL]
                state['invalid'] = unexpected[:MAX_DETAIL]
                if duplicate:
                    state['invalid'].append('ZIP 包含重複檔名')
                if not missing and not unexpected and not duplicate:
                    read_verified_zip(path)
                    state['state'] = 'verified'
                    state['verified_entries'] = 2
    except (OSError, BadZipFile, ValueError, KeyError, EOFError,
            UnicodeError, RuntimeError, TypeError):
        # Errors may include private paths or archive contents, so report
        # only a stable diagnosis. Never trust damaged input as complete.
        state['invalid'].append('固定 SHA-256／Schema／ZIP 結構校驗失敗')
    if state['state'] == 'invalid' and not state['invalid'] and not state['missing']:
        state['invalid'].append('正式封裝格式不完整')
    state['invalid'] = state['invalid'][:MAX_DETAIL + 1]
    return state


def diagnose_resources(*, base=None, checked_at_utc=None):
    """Independently check each pinned formal source and report missing groups."""
    from wlre.services.world.runtime_1275 import FOLDER
    root = Path(base) if base is not None else data_root()
    formal = root / FOLDER
    sources = {name: _inspect_archive(formal / name, name)
               for name in ARCHIVES}
    incomplete = [name for name in ARCHIVES if sources[name]['state'] != 'verified']
    missing_groups = []
    for name in incomplete:
        if sources[name]['state'] == 'missing':
            missing_groups.extend(REQUIRED_GROUPS[name])
        elif sources[name]['missing']:
            missing_groups.extend(sources[name]['missing'])
    return {
        'schema_version': SCHEMA,
        'checked_at_utc': (checked_at_utc if checked_at_utc is not None else
                           datetime.now(timezone.utc).isoformat(timespec='seconds')),
        'formal_sources': sources,
        'missing_groups': missing_groups[:MAX_DETAIL],
        'formal_ready': not incomplete,
        'protocol_compatibility': 'unverified',
        'assets_ready': False, 'can_send_packets': False,
    }


def report_path(base=None):
    root = Path(base) if base is not None else data_root()
    return root / 'official_sync' / FILENAME


def save_report(report, *, base=None):
    """Atomic read-only diagnostic receipt, not an authorization artifact."""
    if (type(report) is not dict or report.get('schema_version') != SCHEMA
            or report.get('assets_ready') is not False
            or report.get('can_send_packets') is not False):
        raise ValueError('Unsafe diagnostic report')
    payload = (json.dumps(report, ensure_ascii=True, sort_keys=True,
                          separators=(',', ':')) + '\n').encode('utf-8')
    if not 0 < len(payload) <= MAX_REPORT_BYTES:
        raise ValueError('Diagnostic report exceeds size cap')
    target = report_path(base)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.gap_',
                                         suffix='.partial', delete=False) as fd:
            temporary = Path(fd.name)
            fd.write(payload)
            fd.flush()
            os.fsync(fd.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def read_report(*, base=None, expected_checked_at_utc=None):
    try:
        raw = report_path(base).read_bytes()
        if not 0 < len(raw) <= MAX_REPORT_BYTES:
            return None
        doc = json.loads(raw)
        if (type(doc) is not dict or set(doc) != {
                'schema_version', 'checked_at_utc', 'formal_sources',
                'missing_groups', 'formal_ready', 'protocol_compatibility',
                'assets_ready', 'can_send_packets'}
                or doc['schema_version'] != SCHEMA
                or type(doc['checked_at_utc']) is not str
                or len(doc['checked_at_utc']) > 40
                or (expected_checked_at_utc is not None and
                    doc['checked_at_utc'] != expected_checked_at_utc)
                or type(doc['formal_sources']) is not dict
                or set(doc['formal_sources']) != set(ARCHIVES)
                or type(doc['missing_groups']) is not list
                or len(doc['missing_groups']) > MAX_DETAIL
                or any(type(x) is not str or len(x) > 120
                       for x in doc['missing_groups'])
                or type(doc['formal_ready']) is not bool
                or doc['protocol_compatibility'] != 'unverified'
                or doc['assets_ready'] is not False
                or doc['can_send_packets'] is not False):
            return None
        for name in ARCHIVES:
            row = doc['formal_sources'][name]
            if (type(row) is not dict or set(row) != {
                    'state', 'missing', 'invalid', 'verified_entries', 'required_entries'}
                    or row['state'] not in STATES or
                    type(row['verified_entries']) is not int
                    or row['verified_entries'] < 0 or
                    row['required_entries'] != (163 if name == ARCHIVES[0] else 2)
                    or any(type(row[k]) is not list or len(row[k]) > MAX_DETAIL+1
                           or any(type(s) is not str or len(s) > 120 for s in row[k])
                           for k in ('missing', 'invalid'))):
                return None
        if doc['formal_ready'] != all(
                doc['formal_sources'][name]['state'] == 'verified'
                for name in ARCHIVES):
            return None
        return doc
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return None


def summarize(report):
    if report is None:
        return '正式資源缺口尚未檢查'
    entries = report['formal_sources']
    missing = [name.removesuffix('.zip') for name in ARCHIVES
               if entries[name]['state'] == 'missing']
    broken = [name.removesuffix('.zip') for name in ARCHIVES
              if entries[name]['state'] == 'invalid']
    if not missing and not broken:
        return '完整正式 1275 雙 ZIP 均已校驗；協定仍需審核'
    sections = []
    if missing:
        sections.append('缺少：' + '、'.join(missing))
    if broken:
        sections.append('損壞或內容不符：' + '、'.join(broken))
    return '｜'.join(sections) + '；登入仍受安全限制'
