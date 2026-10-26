"""內容定址快取及跨程序 CAS 指標；磁碟收據本身不授予資料使用權限。"""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from wlre.core.primitives import identifier
from wlre.storage.atomic import file_lock, write_json

MAX_RECEIPT_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024
_SHA = re.compile(r'[0-9a-f]{64}\Z')


class SnapshotError(ValueError):
    pass


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError('duplicate_snapshot_json_key')
        result[key] = value
    return result


def _invalid_constant(_):
    raise SnapshotError('non_json_snapshot_constant')


class SnapshotStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def _path(self, *parts):
        path = self.root.joinpath(*parts)
        if not path.resolve().is_relative_to(self.root):
            raise SnapshotError('snapshot_path_outside_cache')
        return path

    def _pointer(self, scope):
        return self._path('scopes', identifier(scope) + '.json')

    def _blob(self, digest):
        if type(digest) is not str or not _SHA.fullmatch(digest):
            raise SnapshotError('invalid_snapshot_digest')
        return self._path('objects', digest)

    def put(self, raw):
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_BYTES:
            raise SnapshotError('snapshot_source_size_invalid')
        digest = hashlib.sha256(raw).hexdigest()
        target = self._blob(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        pending = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.snapshot_',
                                             suffix='.partial', delete=False) as stream:
                pending = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pending, target)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
        return digest

    def read(self, digest, *, limit=MAX_SOURCE_BYTES):
        if type(limit) is not int or not 0 < limit <= MAX_SOURCE_BYTES:
            raise SnapshotError('invalid_snapshot_read_limit')
        try:
            with self._blob(digest).open('rb') as stream:
                raw = stream.read(limit + 1)
            if not 0 < len(raw) <= limit or hashlib.sha256(raw).hexdigest() != digest:
                raise SnapshotError('snapshot_blob_integrity_failed')
            return raw
        except OSError:
            raise SnapshotError('snapshot_blob_unavailable') from None

    def current_id(self, scope):
        path = self._pointer(scope)
        try:
            with path.open('rb') as stream:
                raw = stream.read(1025)
        except FileNotFoundError:
            return None
        try:
            if len(raw) > 1024:
                raise SnapshotError('snapshot_pointer_too_large')
            value = json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)
            if (type(value) is not dict or set(value) != {'snapshot'}
                    or type(value['snapshot']) is not str or not _SHA.fullmatch(value['snapshot'])):
                raise SnapshotError('snapshot_pointer_invalid')
            return value['snapshot']
        except (UnicodeError, ValueError, RecursionError):
            raise SnapshotError('snapshot_pointer_invalid') from None

    def commit(self, scope, document, *, expected_current):
        """只有預期指標未變才切換；晚到的工作不能覆蓋另一批已驗收快照。"""
        identifier(scope)
        if expected_current is not None:
            self._blob(expected_current)
        raw = json.dumps(document, ensure_ascii=False, sort_keys=True, allow_nan=False,
                         separators=(',', ':')).encode('utf-8')
        if not 0 < len(raw) <= MAX_RECEIPT_BYTES:
            raise SnapshotError('snapshot_receipt_too_large')
        digest = self.put(raw)
        pointer = self._pointer(scope)
        self._path('scopes', scope + '.json.lock')
        with file_lock(pointer):
            if self.current_id(scope) != expected_current:
                raise SnapshotError('snapshot_changed_during_refresh')
            write_json(pointer, {'snapshot': digest})
        return digest

    def diagnose(self, scope):
        """明確只供診斷：沒有重新向官方核對，不能作為正式查詢服務。"""
        digest = self.current_id(scope)
        if digest is None:
            return None
        try:
            document = json.loads(self.read(digest, limit=MAX_RECEIPT_BYTES),
                                  object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)
            if type(document) is not dict:
                raise SnapshotError('snapshot_receipt_invalid')
        except (UnicodeError, ValueError, RecursionError):
            raise SnapshotError('snapshot_receipt_invalid') from None
        return {'status': 'unverified_cache_diagnostic_only', 'snapshot': digest,
                'document': document}
