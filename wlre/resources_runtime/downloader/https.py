"""順序、有界、可取消下載；完整性通過前不改動既有檔案。"""
from __future__ import annotations

import hashlib
import math
import os
import re
import socket
import ssl
import tempfile
import time
import zlib
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from wlre.core.application.diagnostics import DiagnosticLog
from wlre.core.primitives import check_cancelled
from wlre.resources_runtime.official.source import validate_url

CHUNK_BYTES = 64 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_MEMORY_BYTES = 8 * 1024 * 1024


class DownloadError(ValueError):
    def __init__(self, code, *, http_status=None, failure_kind=None):
        super().__init__(code)
        self.http_status = http_status
        self.failure_kind = failure_kind


@dataclass(frozen=True)
class FileIntegrity:
    size: int
    md5: str
    crc32_le: str

    def __post_init__(self):
        if (type(self.size) is not int or not 0 < self.size <= MAX_FILE_BYTES
                or not isinstance(self.md5, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', self.md5)
                or not isinstance(self.crc32_le, str)
                or not re.fullmatch(r'[0-9a-fA-F]{8}', self.crc32_le)):
            raise ValueError('invalid_manifest_file_integrity')


@dataclass(frozen=True)
class DownloadProgress:
    received: int
    expected: int | None
    attempt: int


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            fp.close()
        raise DownloadError('official_redirect_rejected')


class DownloadManager:
    def __init__(self, *, opener=None, timeout=5, total_timeout=120, retries=2,
                 clock=time.monotonic, sleeper=time.sleep, diagnostics=None):
        for value in (timeout, total_timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 300:
                raise ValueError('invalid_download_timeout')
        if type(retries) is not int or not 0 <= retries <= 3:
            raise ValueError('invalid_download_retries')
        self._opener = opener if opener is not None else build_opener(NoRedirect()).open
        self._timeout, self._total_timeout, self._retries = timeout, total_timeout, retries
        self._clock, self._sleeper = clock, sleeper
        self._closed = Event()
        self._owns_diagnostics = diagnostics is None
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticLog()
        if not isinstance(self.diagnostics, DiagnosticLog):
            raise TypeError('download_diagnostic_log_required')

    def close(self):
        self._closed.set()
        if self._owns_diagnostics:
            self.diagnostics.close()

    def __enter__(self):
        check_cancelled(self._closed)
        return self

    def __exit__(self, *_):
        self.close()

    def _remaining(self, deadline, cancel_event):
        check_cancelled(cancel_event)
        if self._closed.is_set():
            raise InterruptedError('download_manager_closed')
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise DownloadError('official_download_deadline_exceeded')
        return remaining

    def _open(self, url, deadline, cancel_event, *, headers=None, method='GET'):
        validate_url(url)
        timeout = min(self._timeout, self._remaining(deadline, cancel_event))
        request_headers = {'User-Agent': 'WLRe-LaLa-ResourcePipeline/1',
                           'Accept': '*/*', 'Accept-Encoding': 'identity', 'Cache-Control': 'no-cache'}
        request_headers.update(headers or {})
        return self._opener(Request(url, headers=request_headers, method=method), timeout=timeout)

    @staticmethod
    def _declared(response):
        value = response.headers.get('Content-Length') if hasattr(response, 'headers') else None
        if value is None:
            return None
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
            raise DownloadError('invalid_content_length')
        return int(value)

    @staticmethod
    def _response(response, url, status=200):
        if response.geturl() != url or getattr(response, 'status', 200) != status:
            raise DownloadError('unexpected_official_response')
        encoding = response.headers.get('Content-Encoding', 'identity') if hasattr(response, 'headers') else 'identity'
        if encoding.lower() not in ('', 'identity'):
            raise DownloadError('unsupported_transport_encoding')

    def _chunks(self, response, *, limit, deadline, cancel_event):
        received = 0
        # HTTPResponse.read1 每次只做一次底層讀取，慢速串流也能檢查總時限。
        read = getattr(response, 'read1', response.read)
        while True:
            self._remaining(deadline, cancel_event)
            chunk = read(min(CHUNK_BYTES, limit - received + 1))
            self._remaining(deadline, cancel_event)
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise DownloadError('non_binary_official_response')
            received += len(chunk)
            if received > limit:
                raise DownloadError('official_download_size_exceeded')
            yield chunk

    def _retry(self, operation, cancel_event):
        deadline = self._clock() + self._total_timeout
        last_status, last_kind = None, 'network'
        for attempt in range(self._retries + 1):
            self._remaining(deadline, cancel_event)
            self.diagnostics.record('downloads', 'attempt_started', attempt=attempt)
            try:
                return operation(deadline, attempt)
            except InterruptedError:
                self.diagnostics.record('downloads', 'cancelled')
                raise
            except DownloadError:
                self.diagnostics.record('downloads', 'validation_failed')
                raise
            except HTTPError as error:
                code = error.code
                error.close()
                last_status = code
                # 429 尊重官方節流，不自動重試或改用其他來源。
                if not 500 <= code <= 599:
                    raise DownloadError('official_http_request_rejected', http_status=code) from None
            except (OSError, URLError, HTTPException) as error:
                # 連線／讀取錯誤有限次重試，不重試格式、來源或完整性失敗。
                reason = error.reason if isinstance(error, URLError) else error
                last_status = None
                last_kind = ('tls' if isinstance(reason, ssl.SSLError) else
                             'protocol' if isinstance(reason, HTTPException) else
                             'dns' if isinstance(reason, socket.gaierror) else
                             'timeout' if isinstance(reason, TimeoutError) else
                             'refused' if isinstance(reason, ConnectionRefusedError) else 'network')
            if attempt == self._retries:
                self.diagnostics.record('downloads', 'retries_exhausted', attempts=attempt + 1)
                raise DownloadError('official_network_retries_exhausted',
                                    http_status=last_status, failure_kind=last_kind) from None
            self.diagnostics.record('downloads', 'retry_scheduled', attempt=attempt + 1)
            delay = min(2.0, 0.25 * 2 ** attempt, self._remaining(deadline, cancel_event))
            if cancel_event is not None:
                if cancel_event.wait(delay):
                    check_cancelled(cancel_event)
            else:
                self._sleeper(delay)

    def read(self, url, *, limit, cancel_event=None):
        validate_url(url)
        if type(limit) is not int or not 1 <= limit <= MAX_MEMORY_BYTES:
            raise ValueError('invalid_download_memory_limit')

        def operation(deadline, attempt):
            with self._open(url, deadline, cancel_event) as response:
                self._response(response, url)
                declared = self._declared(response)
                if declared is not None and declared > limit:
                    raise DownloadError('official_download_size_exceeded')
                body = b''.join(self._chunks(response, limit=limit, deadline=deadline, cancel_event=cancel_event))
                if not body or (declared is not None and len(body) != declared):
                    raise DownloadError('official_response_empty_or_truncated')
                self.diagnostics.record('downloads', 'response_read', received=len(body))
                return body

        return self._retry(operation, cancel_event)

    def _ranges(self, url, integrity, segments, deadline, cancel_event):
        if segments == 1:
            return [(0, integrity.size - 1)], None
        try:
            with self._open(url, deadline, cancel_event, method='HEAD') as response:
                self._response(response, url)
                if (self._declared(response) != integrity.size or
                        response.headers.get('Accept-Ranges', '').lower() != 'bytes'):
                    return [(0, integrity.size - 1)], None
                etag = response.headers.get('ETag')
                if not isinstance(etag, str) or not re.fullmatch(r'"[^"\r\n]{1,128}"', etag):
                    return [(0, integrity.size - 1)], None
        except HTTPError as error:
            if error.code not in (405, 501):
                raise
            error.close()
            return [(0, integrity.size - 1)], None
        count = min(segments, integrity.size)
        step = math.ceil(integrity.size / count)
        return [(start, min(start + step, integrity.size) - 1)
                for start in range(0, integrity.size, step)], etag

    def verify_file(self, path, integrity, *, cancel_event=None):
        check_cancelled(self._closed)
        check_cancelled(cancel_event)
        if not isinstance(integrity, FileIntegrity):
            raise TypeError('file_integrity_required')
        path = Path(path)
        if not path.is_file() or path.stat().st_size != integrity.size:
            return False
        md5, crc, total = hashlib.md5(usedforsecurity=False), 0, 0
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(CHUNK_BYTES), b''):
                check_cancelled(self._closed)
                check_cancelled(cancel_event)
                md5.update(chunk)
                crc = zlib.crc32(chunk, crc)
                total += len(chunk)
        check_cancelled(cancel_event)
        return (total == integrity.size and md5.hexdigest() == integrity.md5.lower()
                and (crc & 0xffffffff).to_bytes(4, 'little').hex() == integrity.crc32_le.lower())

    def download(self, url, integrity, destination, *, cancel_event=None, progress=None, segments=1):
        """destination 由應用程式決定，禁止使用未驗證的遠端資產路徑。"""
        validate_url(url)
        if not isinstance(integrity, FileIntegrity):
            raise TypeError('file_integrity_required')
        if type(segments) is not int or not 1 <= segments <= 4:
            raise ValueError('invalid_download_segments')
        destination = Path(destination)
        check_cancelled(self._closed)
        check_cancelled(cancel_event)
        if self.verify_file(destination, integrity, cancel_event=cancel_event):
            self.diagnostics.record('downloads', 'verified_cache_hit', size=integrity.size)
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)

        def operation(deadline, attempt):
            ranges, etag = self._ranges(url, integrity, segments, deadline, cancel_event)
            pending = None
            md5, crc, total = hashlib.md5(usedforsecurity=False), 0, 0
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.official_',
                                                 suffix='.partial', delete=False) as handle:
                    pending = Path(handle.name)
                    for start, end in ranges:
                        headers = {'Range': f'bytes={start}-{end}', 'If-Range': etag} if etag else None
                        with self._open(url, deadline, cancel_event, headers=headers) as response:
                            self._response(response, url, 206 if etag else 200)
                            expected = end - start + 1
                            declared = self._declared(response)
                            if declared is not None and declared != expected:
                                raise DownloadError('bundle_size_differs_from_manifest')
                            if etag and response.headers.get('Content-Range') != f'bytes {start}-{end}/{integrity.size}':
                                raise DownloadError('invalid_official_content_range')
                            segment_size = 0
                            for chunk in self._chunks(response, limit=expected, deadline=deadline,
                                                      cancel_event=cancel_event):
                                segment_size += len(chunk)
                                total += len(chunk)
                                md5.update(chunk)
                                crc = zlib.crc32(chunk, crc)
                                handle.write(chunk)
                                if progress is not None:
                                    progress(DownloadProgress(total, integrity.size, attempt))
                            if segment_size != expected:
                                raise DownloadError('official_bundle_truncated')
                    handle.flush()
                    os.fsync(handle.fileno())
                self._remaining(deadline, cancel_event)
                if (total != integrity.size or md5.hexdigest() != integrity.md5.lower() or
                        (crc & 0xffffffff).to_bytes(4, 'little').hex() != integrity.crc32_le.lower()):
                    raise DownloadError('official_bundle_integrity_failed')
                os.replace(pending, destination)
                self.diagnostics.record('downloads', 'file_verified', received=total)
                return destination
            finally:
                if pending is not None:
                    pending.unlink(missing_ok=True)

        return self._retry(operation, cancel_event)
