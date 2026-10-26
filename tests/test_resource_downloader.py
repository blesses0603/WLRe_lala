"""官方 HTTPS 共用傳輸的錯誤／取消／原子性測試，完全不連線。"""
import hashlib
import io
import tempfile
import unittest
import zlib
from http.client import IncompleteRead
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.request import Request

from wlre.core.application.diagnostics import DiagnosticLog
from wlre.resources_runtime.downloader import (
    DownloadError,
    DownloadManager,
    FileIntegrity,
)
from wlre.resources_runtime.downloader.https import NoRedirect
from wlre.resources_runtime.official.source import ROOT, validate_url

URL = ROOT + '/1.3.21/ResourcesPC/AssetBundle/test.bundle'


def integrity(data):
    return FileIntegrity(len(data), hashlib.md5(data, usedforsecurity=False).hexdigest(),
                         (zlib.crc32(data) & 0xffffffff).to_bytes(4, 'little').hex())


class Response(io.BytesIO):
    def __init__(self, data, url=URL, *, status=200, headers=None):
        super().__init__(data)
        self.url, self.status = url, status
        self.headers = {'Content-Length': str(len(data))} if headers is None else headers

    def geturl(self):
        return self.url


class DownloaderTests(unittest.TestCase):
    def test_source_policy_rejects_spoof_traversal_and_unbounded_listing(self):
        for url in ('http://' + URL.removeprefix('https://'), ROOT + '/',
                    URL.replace('chinesegamer.net', 'chinesegamer.net.evil.example'),
                    ROOT + '/1.3.21/ResourcesPC/AssetBundle/../../private', URL + '?token=private',
                    ROOT + '/1.3.21/ResourcesPC/AssetBundle/%2e%2e/test.bundle'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_small_read_checks_origin_length_limit_and_content(self):
        manager = DownloadManager(opener=lambda request, timeout: Response(b'data'))
        self.assertEqual(manager.read(URL, limit=4), b'data')
        for response in (Response(b'12345'), Response(b'ab', headers={'Content-Length': '4'}),
                         Response(b'data', url='https://evil.example/x'), Response(b'')):
            with self.subTest(response=response), self.assertRaises(DownloadError):
                DownloadManager(opener=lambda request, timeout, r=response: r).read(URL, limit=4)

    def test_retry_is_finite_and_only_transient_http_statuses_retry(self):
        attempts, waits = [], []

        def flaky(request, timeout):
            attempts.append(request.full_url)
            if len(attempts) < 3:
                raise HTTPError(URL, 503, 'unavailable', {}, io.BytesIO())
            return Response(b'good')

        manager = DownloadManager(opener=flaky, sleeper=waits.append)
        self.assertEqual(manager.read(URL, limit=4), b'good')
        self.assertEqual(len(attempts), 3)
        self.assertEqual(waits, [0.25, 0.5])
        self.assertEqual([r.code for r in manager.diagnostics.snapshot()].count('retry_scheduled'), 2)

        failures = []

        def unavailable(request, timeout):
            failures.append(True)
            raise URLError('test-only-private-details')

        manager = DownloadManager(opener=unavailable, sleeper=lambda delay: None, retries=1)
        with self.assertRaisesRegex(DownloadError, '^official_network_retries_exhausted$'):
            manager.read(URL, limit=4)
        self.assertEqual(len(failures), 2)
        self.assertNotIn('private-details', repr(manager.diagnostics.snapshot()))

    def test_nonretryable_status_does_not_loop(self):
        for status in (404, 429):
            attempts = []

            def missing(request, timeout, status=status, attempts=attempts):
                attempts.append(True)
                raise HTTPError(URL, status, 'not found', {}, io.BytesIO())

            with self.subTest(status=status), self.assertRaises(DownloadError):
                DownloadManager(opener=missing).read(URL, limit=10)
            self.assertEqual(len(attempts), 1)

    def test_redirect_rejection_releases_http_response(self):
        response = Response(b'')
        with self.assertRaises(DownloadError):
            NoRedirect().redirect_request(Request(URL), response, 302, 'redirect', {}, URL)
        self.assertTrue(response.closed)

    def test_closing_downloader_does_not_close_borrowed_application_log(self):
        diagnostics = DiagnosticLog()
        manager = DownloadManager(diagnostics=diagnostics)
        manager.close()
        diagnostics.record('application', 'still_running')
        self.assertEqual(diagnostics.snapshot()[-1].code, 'still_running')

    def test_deadline_stops_slow_response_and_does_not_reset_per_chunk(self):
        now = [0.0]

        class Slow(Response):
            def read1(self, size):
                now[0] += 0.6
                return super().read1(1)

        manager = DownloadManager(opener=lambda request, timeout: Slow(b'1234'),
                                  total_timeout=1, clock=lambda: now[0])
        with self.assertRaisesRegex(DownloadError, '^official_download_deadline_exceeded$'):
            manager.read(URL, limit=4)

    def test_cancel_and_close_prevent_network_requests(self):
        cancelled = Event()
        cancelled.set()

        def forbidden(request, timeout):
            self.fail('unexpected network request')

        manager = DownloadManager(opener=forbidden)
        with self.assertRaises(InterruptedError):
            manager.read(URL, limit=4, cancel_event=cancelled)
        manager.close()
        with self.assertRaises(InterruptedError):
            manager.read(URL, limit=4)

    def test_atomic_verified_download_and_cache_reuse(self):
        body, requested, progress = b'known fixture content', [], []

        def opener(request, timeout):
            requested.append(request.get_method())
            return Response(body)

        manager = DownloadManager(opener=opener)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'content.bundle'
            manager.download(URL, integrity(body), path, progress=progress.append)
            self.assertEqual(path.read_bytes(), body)
            manager.download(URL, integrity(body), path)
            self.assertEqual(requested, ['GET'])
            self.assertEqual(progress[-1].received, len(body))
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_invalid_hash_never_overwrites_old_file_or_leaves_partial(self):
        manager = DownloadManager(opener=lambda request, timeout: Response(b'bad'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'content.bundle'
            path.write_bytes(b'old')
            with self.assertRaises(DownloadError):
                manager.download(URL, integrity(b'new'), path)
            self.assertEqual(path.read_bytes(), b'old')
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_interrupted_body_retry_restarts_atomic_file_without_mixing_partial_bytes(self):
        calls = []

        class Interrupted(Response):
            def read1(self, size):
                if self.tell() == 0:
                    return super().read1(2)
                raise IncompleteRead(b'private-partial-test-data', 2)

        def recover(request, timeout):
            calls.append(True)
            return Interrupted(b'bad!') if len(calls) == 1 else Response(b'good')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'content.bundle'
            manager = DownloadManager(opener=recover, sleeper=lambda delay: None)
            manager.download(URL, integrity(b'good'), path)
            self.assertEqual(path.read_bytes(), b'good')
            self.assertEqual(len(calls), 2)
            self.assertEqual(list(Path(directory).iterdir()), [path])
            self.assertNotIn('private-partial-test-data', repr(manager.diagnostics.snapshot()))

    def test_cancel_mid_download_keeps_old_file_and_cleans_partial(self):
        cancelled = Event()
        manager = DownloadManager(opener=lambda request, timeout: Response(b'new'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'content.bundle'
            path.write_bytes(b'old')
            with self.assertRaises(InterruptedError):
                manager.download(URL, integrity(b'new'), path,
                                 cancel_event=cancelled, progress=lambda status: cancelled.set())
            self.assertEqual(path.read_bytes(), b'old')
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_ranges_require_advertised_support_and_strong_etag(self):
        body, requests = b'0123456789abcdef', []

        def ranged(request, timeout):
            headers = {name.lower(): value for name, value in request.header_items()}
            if request.get_method() == 'HEAD':
                return Response(b'', headers={'Content-Length': str(len(body)),
                                              'Accept-Ranges': 'bytes', 'ETag': '"test-v1"'})
            self.assertEqual(headers['if-range'], '"test-v1"')
            start, end = map(int, headers['range'].removeprefix('bytes=').split('-'))
            requests.append((start, end))
            return Response(body[start:end + 1], status=206,
                            headers={'Content-Length': str(end - start + 1),
                                     'Content-Range': f'bytes {start}-{end}/{len(body)}'})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'content.bundle'
            DownloadManager(opener=ranged).download(URL, integrity(body), path, segments=4)
            self.assertEqual(path.read_bytes(), body)
        self.assertEqual(b''.join(body[start:end + 1] for start, end in requests), body)
        self.assertLessEqual(len(requests), 4)

    def test_unadvertised_ranges_fall_back_to_single_get(self):
        body, methods = b'file', []

        def unsupported(request, timeout):
            methods.append(request.get_method())
            if request.get_method() == 'HEAD':
                raise HTTPError(URL, 405, 'unsupported', {}, io.BytesIO())
            self.assertIsNone(request.get_header('Range'))
            return Response(body)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'content.bundle'
            DownloadManager(opener=unsupported).download(URL, integrity(body), path, segments=4)
            self.assertEqual(path.read_bytes(), body)
        self.assertEqual(methods, ['HEAD', 'GET'])

    def test_bad_range_never_publishes_mixed_content(self):
        body = b'0123456789abcdef'

        def incorrect(request, timeout):
            if request.get_method() == 'HEAD':
                return Response(b'', headers={'Content-Length': str(len(body)),
                                              'Accept-Ranges': 'bytes', 'ETag': '"test-v1"'})
            return Response(body[:4], status=206,
                            headers={'Content-Length': '4', 'Content-Range': 'bytes 1-4/16'})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'content.bundle'
            path.write_bytes(b'old')
            with self.assertRaises(DownloadError):
                DownloadManager(opener=incorrect).download(URL, integrity(body), path, segments=4)
            self.assertEqual(path.read_bytes(), b'old')
            self.assertEqual(list(Path(directory).iterdir()), [path])
