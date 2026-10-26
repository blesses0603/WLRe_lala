"""動態版本觀測及正式解析器邊界，不發出 HTTP 或授予遊戲權限。"""
import json
import unittest
from threading import Event

from wlre.resources_runtime.official.source import ROOT, package_url
from wlre.resources_runtime.official.versions import (
    VersionDetector,
    VersionObservationError,
)
from wlre.resources_runtime.parsers import ParseError, parse_manifest
from wlre.services.official_version import VersionSourceError, validate_source


class OfficialResourceVersionTests(unittest.TestCase):
    def fixture(self):
        # 明確的模擬新版資料，只驗證觀測不綁 1262／1275；不是實機驗收。
        resource_map = json.dumps([{'ExeVer': '2.0.0', 'DataVer': '9.8.7'}]).encode()
        return {ROOT + '/ResourcePath_PC.dat': resource_map,
                package_url('9.8.7', 'DataPackage', 'version'): b'9999_data_build',
                package_url('9.8.7', 'MainPackage', 'version'): b'9999_main_build'}

    def test_observe_future_versions_without_granting_runtime_permission(self):
        files = self.fixture()
        observed = VersionDetector(fetcher=files.__getitem__).observe('2.0.0')
        self.assertEqual(observed.data_version, '9.8.7')
        self.assertEqual(observed.data_package_version, '9999_data_build')
        self.assertEqual(observed.main_package_version, '9999_main_build')
        self.assertEqual(observed.observed_exe_version, '2.0.0')
        self.assertFalse(hasattr(observed, 'login_approved'))

    def test_torn_version_observation_is_not_returned_as_valid(self):
        files, calls = self.fixture(), []

        def changed(url):
            calls.append(url)
            if len(calls) > 3 and url.endswith('DataPackage.version'):
                return b'10000_changed_build'
            return files[url]

        with self.assertRaises(VersionObservationError):
            VersionDetector(fetcher=changed).observe('2.0.0')
        self.assertEqual(len(calls), 6)

    def test_unknown_client_does_not_guess_a_mapping(self):
        files = self.fixture()
        with self.assertRaises(VersionSourceError):
            VersionDetector(fetcher=files.__getitem__).observe('3.0.0')
        for value in (None, '', '../2.0.0'):
            with self.subTest(value=value), self.assertRaises(VersionObservationError):
                VersionDetector(fetcher=lambda url: self.fail('invalid identity fetched')).observe(value)

    def test_cancelled_observation_never_fetches(self):
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            VersionDetector(fetcher=lambda url: self.fail('unexpected request')).observe(
                '2.0.0', cancel_event=cancelled)

    def test_new_authority_required_and_package_paths_cannot_escape(self):
        with self.assertRaises(VersionSourceError):
            validate_source('https://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat')
        for data_version in ('../9.8.7', '9.8.7/../../x', '9.8.7?x=1'):
            with self.assertRaises(ValueError):
                package_url(data_version, 'DataPackage', 'bytes')

    def test_legacy_parser_api_is_same_implementation(self):
        from tools.resources.lala_manifest_full_index import parse_manifest as legacy
        self.assertIs(legacy, parse_manifest)
        for raw in (b'', b'unknown format', bytes(8 * 1024 * 1024 + 1)):
            with self.assertRaises(ParseError):
                parse_manifest(raw)
