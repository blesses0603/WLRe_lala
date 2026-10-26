"""取消必須停止後續請求，且不能覆寫已驗證更新；所有 HTTP 皆為測試替身。"""
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import test_lala_updater as updater_fixtures

from wlre.services import lala_updater
from wlre.services.game_version_gate import run_prelogin_check
from wlre.services.official_version import check_official_game_resources


class VersionCancellationTests(unittest.TestCase):
    def test_pre_cancelled_gate_never_checks_network_or_enables_login(self):
        cancelled = Event()
        cancelled.set()
        checker = Mock(side_effect=AssertionError('must not be called'))
        with self.assertRaises(InterruptedError):
            run_prelogin_check(checker=checker, cancel_event=cancelled)
        checker.assert_not_called()

    def test_cancel_after_first_response_stops_further_package_requests(self):
        cancelled, requested = Event(), []

        def fetcher(url):
            requested.append(url)
            cancelled.set()
            return b'[{"ExeVer":"1.3.0","DataVer":"1.3.21"}]'

        with self.assertRaises(InterruptedError):
            check_official_game_resources(fetcher=fetcher, cancel_event=cancelled)
        self.assertEqual(len(requested), 1)


class ReleaseCancellationTests(unittest.TestCase):
    def test_cancel_during_stream_keeps_existing_verified_archive_and_removes_partial(self):
        # 沿用既有更新測試的明確模擬 Release，並非真實安裝包。
        fixture = updater_fixtures.UpdaterTests()
        fixture.setUp()
        try:
            opener = fixture.fake_opener()
            info = lala_updater.check_lala_release(current_version='0.5.17', opener=opener)
            cancelled = Event()

            class CancelAfterRead(updater_fixtures.Response):
                def read(self, *args):
                    result = super().read(*args)
                    cancelled.set()
                    return result

            def interrupted(request, *, timeout):
                response = opener(request, timeout=timeout)
                if request.full_url.endswith('.zip'):
                    return CancelAfterRead(response.read())
                return response

            with tempfile.TemporaryDirectory() as directory:
                old = lala_updater.download_verified_release(info, directory=directory, opener=opener)
                original = old.read_bytes()
                with self.assertRaises(lala_updater.UpdateError):
                    lala_updater.download_verified_release(
                        info, directory=directory, opener=interrupted, cancel_event=cancelled)
                self.assertEqual(old.read_bytes(), original)
                self.assertEqual(list(Path(directory).iterdir()), [old])
        finally:
            fixture.doCleanups()

    def test_pre_cancelled_release_request_does_not_open_connection(self):
        cancelled = Event()
        cancelled.set()
        opener = Mock(side_effect=AssertionError('must not connect'))
        with self.assertRaises(InterruptedError):
            lala_updater.check_lala_release(opener=opener, cancel_event=cancelled)
        opener.assert_not_called()
