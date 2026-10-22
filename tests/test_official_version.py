"""Offline tests based on the user's observed Fiddler PC requests."""
import io
import gzip
import socket
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from wlre.services.official_version import (
    BASELINE, BASELINE_MANIFEST, RESOURCE_MAP_URL, VersionSourceError,
    check_official_game_resources, check_official_versions, compare_versions,
    fetch_bytes, fetch_version, official_package_urls,
    parse_resource_path, parse_version, validate_source,
    _request_problem, InvalidResourceBody,
)

RESOURCE_MAP = b'''[
{"ExeVer":"1.1.3","DataVer":"1.3.21"},
{"ExeVer":"1.1.4","DataVer":"1.3.21"},
{"ExeVer":"1.2.0","DataVer":"1.3.21"},
{"ExeVer":"1.3.0","DataVer":"1.3.21"}
]'''
MAIN = "https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/MainPackage.version"
DATA = "https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/DataPackage.version"
MAIN_VALUE = b"1275_2026_10_21_18_29_38_49"
DATA_VALUE = b"1275_2026_10_21_18_27_33_84"


class FakeResponse(io.BytesIO):
    def __init__(self, body, url):
        super().__init__(body)
        self.url = url
        self.status = 200

    def geturl(self):
        return self.url


class OfficialResourceVersionTests(unittest.TestCase):
    def test_real_observed_url_shape(self):
        self.assertEqual(official_package_urls("1.3.21"), {"MainPackage": MAIN, "DataPackage": DATA})
        for url in (RESOURCE_MAP_URL, MAIN, DATA, MAIN + "?1729600000"):
            self.assertEqual(validate_source(url), url)

    def test_reject_unapproved_domains_paths_query_and_credentials(self):
        bad = (
            "http://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat",
            "https://wlreftp.chinesegamer.net.evil.com/WLN/TW/ResourcePath_PC.dat",
            "https://wlreftp.chinesegamer.net@evil.com/WLN/TW/ResourcePath_PC.dat",
            "https://wlreftp.chinesegamer.net:443/WLN/TW/ResourcePath_PC.dat",
            "https://wlreupload.chinesegamer.net/wln/TW/ResourcePath_PC.dat",
            "https://wlreftp.chinesegamer.net/WLN/TW/../../private.version",
            "https://wlreftp.chinesegamer.net/WLN/TW/%2e%2e/ResourcePath_PC.dat",
            "https://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat?token=secret",
            "https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/OtherPackage.version",
            "https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/MainPackage.version#fragment",
        )
        for url in bad:
            with self.subTest(url=url), self.assertRaises(VersionSourceError):
                validate_source(url)

    def test_parse_fiddler_exe_ver_mapping(self):
        got = parse_resource_path(RESOURCE_MAP)
        self.assertEqual(got["exe_version"], "1.3.0")
        self.assertEqual(got["data_version"], "1.3.21")
        self.assertEqual(got["newer_exe_versions"], [])

    def test_unknown_exe_version_is_unverified(self):
        with self.assertRaises(VersionSourceError):
            parse_resource_path(RESOURCE_MAP, exe_version="2.0.0")

    def test_duplicate_or_malformed_mapping_rejected(self):
        for body in (b'[]', b'{"ExeVer":"1.3.0","DataVer":"1.3.21"}',
                     b'[{"ExeVer":"1.3.0","DataVer":"1.3.21"},'
                     b'{"ExeVer":"1.3.0","DataVer":"1.3.22"}]',
                     b'[{"ExeVer":"1.3.0","DataVer":"../../x"}]'):
            with self.subTest(body=body), self.assertRaises(VersionSourceError):
                parse_resource_path(body)

    def test_supported_client_and_future_client(self):
        new_map = RESOURCE_MAP[:-1] + b',{"ExeVer":"1.4.0","DataVer":"1.3.22"}]'
        parsed = parse_resource_path(new_map)
        self.assertIn("1.4.0", parsed["newer_exe_versions"])
        self.assertEqual(parsed["supported_data_version"], "1.3.21")
        self.assertEqual(parsed["data_version"], "1.3.22")
        self.assertEqual(parsed["selected_exe_version"], "1.4.0")

    def test_complete_remote_lookup_fiddler_1275(self):
        observed = {RESOURCE_MAP_URL: RESOURCE_MAP, MAIN: MAIN_VALUE, DATA: DATA_VALUE}
        got = check_official_game_resources(fetcher=lambda url: observed[url])
        self.assertEqual(got["status"], "resources_changed")
        self.assertEqual(got["resource_path"], "1.3.21")
        self.assertEqual(got["packages"]["MainPackage"]["remote"], MAIN_VALUE.decode())
        self.assertEqual(got["packages"]["DataPackage"]["remote"], DATA_VALUE.decode())
        self.assertEqual(got["packages"]["MainPackage"]["comparison"], "newer")

    def test_live_path_rotates_when_mapping_updates(self):
        updated = RESOURCE_MAP.replace(b"1.3.21", b"1.3.22")
        main22, data22 = official_package_urls("1.3.22").values()
        observed = {RESOURCE_MAP_URL: updated, main22: b"1276_2026_10_22_10_00_00_01",
                    data22: b"1276_2026_10_22_10_00_00_02"}
        got = check_official_game_resources(fetcher=lambda url: observed[url])
        self.assertEqual(got["resource_path"], "1.3.22")
        self.assertEqual(got["packages"]["MainPackage"]["remote"].split("_")[0], "1276")

    def test_resource_path_fetch_fails_without_using_stale_path(self):
        def broken(url):
            raise VersionSourceError("offline")
        got = check_official_game_resources(fetcher=broken)
        self.assertEqual(got["status"], "unverified")
        self.assertIsNone(got["resource_path"])

    def test_partial_change_keeps_explicit_evidence(self):
        def fetcher(url):
            if url == RESOURCE_MAP_URL:
                return RESOURCE_MAP
            if url == MAIN:
                return MAIN_VALUE
            raise VersionSourceError("offline")
        got = check_official_game_resources(fetcher=fetcher)
        self.assertEqual(got["status"], "unverified")
        self.assertEqual(got["packages"]["MainPackage"]["comparison"], "newer")

    def test_embedded_1262_manifest_identifiers_detect_republish(self):
        self.assertEqual(BASELINE_MANIFEST["MainPackage"], "1262_2026_10_14_15_02_22_47")
        self.assertEqual(BASELINE_MANIFEST["DataPackage"], "1262_2026_10_14_15_00_34_84")
        known = {RESOURCE_MAP_URL: RESOURCE_MAP,
                 MAIN: BASELINE_MANIFEST["MainPackage"].encode(),
                 DATA: BASELINE_MANIFEST["DataPackage"].encode()}
        same = check_official_game_resources(fetcher=lambda url: known[url])
        self.assertEqual(same["status"], "same_resources")
        known[MAIN] = b"1262_2026_10_22_11_00_00_00"
        changed = check_official_game_resources(fetcher=lambda url: known[url])
        self.assertEqual(changed["status"], "resources_changed")
        self.assertEqual(changed["packages"]["MainPackage"]["comparison"], "different")
        known[MAIN] = b"1262"
        unknown = check_official_game_resources(fetcher=lambda url: known[url])
        self.assertEqual(unknown["status"], "unverified")

    def test_version_parse_and_compare(self):
        self.assertEqual(parse_version(b"1262"), "1262")
        self.assertEqual(parse_version(MAIN_VALUE), MAIN_VALUE.decode())
        self.assertEqual(parse_version(b'{"packageVersion":"1262"}'), "1262")
        with self.assertRaises(VersionSourceError):
            parse_version(b"<html>not a version</html>")
        self.assertEqual(compare_versions("1262", "1262_2026_10_21_18_29_38_49"), "same")
        self.assertEqual(compare_versions("1262", MAIN_VALUE.decode()), "newer")
        self.assertEqual(compare_versions("1262", "1261_2026_10_21_18_29_38_49"), "older")

    def test_bounded_http_no_cross_host_redirect(self):
        def opener(req, timeout):
            self.assertIn("?1", req.full_url)
            return FakeResponse(b"1262", req.full_url)
        from unittest.mock import patch
        with patch("wlre.services.official_version.time.time", return_value=1.123):
            got = fetch_bytes(MAIN, opener=opener)
        self.assertEqual(got, b"1262")
        def redirect(req, timeout):
            return FakeResponse(b"1262", "https://evil.example.com/test")
        with self.assertRaises(VersionSourceError):
            fetch_version(MAIN, opener=redirect)

    def test_error_diagnostics_identify_stage_without_leaking_url(self):
        def failed_map(url):
            raise VersionSourceError("DNS 無法解析官方網域")
        result = check_official_game_resources(fetcher=failed_map)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["failed_stage"], "ResourcePath_PC.dat")
        self.assertIn("DNS", result["reason"])
        self.assertNotIn("https://", result["reason"])

        def failed_main(url):
            if url == RESOURCE_MAP_URL:
                return RESOURCE_MAP
            if url == MAIN:
                raise VersionSourceError("TLS 憑證驗證失敗")
            return DATA_VALUE
        result = check_official_game_resources(fetcher=failed_main)
        self.assertEqual(result["failed_stage"], "MainPackage.version")
        self.assertEqual(result["packages"]["MainPackage"]["reason"], "TLS 憑證驗證失敗")
        self.assertEqual(result["packages"]["DataPackage"]["comparison"], "newer")

    def test_network_failure_categories(self):
        self.assertIn("DNS", _request_problem(URLError(socket.gaierror(-2, "name unknown"))))
        self.assertIn("HTTP 403", _request_problem(HTTPError(MAIN, 403, "Forbidden", {}, None)))
        self.assertEqual(_request_problem(TimeoutError()), "連線逾時")

    def test_cdn_query_rejection_retries_canonical_once(self):
        called = []
        def opener(req, timeout):
            called.append(req.full_url)
            if "?" in req.full_url:
                raise HTTPError(req.full_url, 403, "cache parameter rejected", {}, None)
            return FakeResponse(b"1275_2026_10_21_18_29_38_49", req.full_url)
        data = fetch_bytes(MAIN, opener=opener)
        self.assertEqual(data, MAIN_VALUE)
        self.assertEqual(len(called), 2)
        self.assertTrue(called[0].startswith(MAIN + "?"))
        self.assertEqual(called[1], MAIN)

    def test_nonrecoverable_http_status_does_not_repeat_requests(self):
        called = []
        def opener(req, timeout):
            called.append(req.full_url)
            raise HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        with self.assertRaisesRegex(VersionSourceError, "HTTP 429"):
            fetch_bytes(MAIN, opener=opener)
        self.assertEqual(len(called), 1)

    def test_map_utf16_and_gzip_and_bad_html_diagnostics(self):
        self.assertEqual(
            parse_resource_path(RESOURCE_MAP.decode("utf-8").encode("utf-16"))["data_version"],
            "1.3.21")
        self.assertEqual(
            parse_resource_path(gzip.compress(RESOURCE_MAP))["data_version"],
            "1.3.21")
        with self.assertRaisesRegex(InvalidResourceBody, r"HTML.*34 bytes"):
            parse_resource_path(b"<html><body>HTTP 200</body></html>")
        with self.assertRaisesRegex(InvalidResourceBody, "gzip 格式無效"):
            parse_resource_path(b"\x1f\x8binvalid")
        with self.assertRaisesRegex(InvalidResourceBody, "不是可讀 JSON"):
            parse_resource_path(b"\xff\xfe\xff")

    def test_live_resource_map_http200_html_falls_back_to_canonical_url(self):
        requests = []
        def observed(url, **kwargs):
            requests.append((url, kwargs))
            if url == RESOURCE_MAP_URL:
                return (RESOURCE_MAP if kwargs.get("cache_bust") is False
                        else b"<html>WAF cache error</html>")
            return MAIN_VALUE if url == MAIN else DATA_VALUE
        with patch("wlre.services.official_version.fetch_bytes", side_effect=observed) as fetch:
            got = check_official_game_resources(fetcher=fetch)
        self.assertEqual(got["status"], "resources_changed")
        self.assertEqual(got["resource_path"], "1.3.21")
        self.assertEqual(requests[0][0], RESOURCE_MAP_URL)
        self.assertEqual(requests[1], (RESOURCE_MAP_URL, {"cache_bust": False}))
        self.assertEqual(len(requests), 4)

    def test_invalid_map_fallback_failure_stays_unknown_not_1262(self):
        calls = []
        def observed(url, **kwargs):
            calls.append((url, kwargs))
            return b"<html>200 but blocked</html>"
        with patch("wlre.services.official_version.fetch_bytes", side_effect=observed) as fetch:
            result = check_official_game_resources(fetcher=fetch)
        self.assertEqual(result["status"], "unverified")
        self.assertIsNone(result["resource_path"])
        self.assertIn("HTML", result["reason"])
        self.assertEqual(len(calls), 2)

    def test_fiddler_164byte_trailing_comma_to_dynamic_datapackage_url(self):
        # Reconstructed from the user's Fiddler ExeVer/DataVer values:
        # CRLF lines and an extra comma before ']' produce exactly 164 bytes.
        response = (
            b'[\r\n'
            b'{"ExeVer":"1.1.3","DataVer":"1.3.21"},\r\n'
            b'{"ExeVer":"1.1.4","DataVer":"1.3.21"},\r\n'
            b'{"ExeVer":"1.2.0","DataVer":"1.3.21"},\r\n'
            b'{"ExeVer":"1.3.0","DataVer":"1.3.21"},\r\n'
            b']'
        )
        self.assertEqual(len(response), 164)
        parsed = parse_resource_path(response, exe_version="1.3.0")
        self.assertEqual(parsed["data_version"], "1.3.21")
        observed = {RESOURCE_MAP_URL: response, DATA: DATA_VALUE, MAIN: MAIN_VALUE}
        order = []

        def fetching(url):
            order.append(url)
            return observed[url]

        checked = check_official_game_resources(fetcher=fetching)
        self.assertEqual(order, [RESOURCE_MAP_URL, DATA, MAIN])
        self.assertEqual(checked["resource_path"], "1.3.21")
        self.assertEqual(checked["packages"]["DataPackage"]["remote"], DATA_VALUE.decode())
        self.assertEqual(checked["status"], "resources_changed")

    def test_only_terminal_array_comma_may_be_repaired(self):
        malformed = (
            b'[{"ExeVer":"1.3.0",,"DataVer":"1.3.21"}]',
            b'[{"ExeVer":"1.3.0","DataVer":"1.3.21"},,]',
            b'[{"ExeVer":"1.3.0","DataVer":"1.3.21" // unsafe comment\n}]',
            b'[{"ExeVer":"1.3.0","DataVer":"../private"},]',
        )
        for text in malformed:
            with self.subTest(text=text), self.assertRaises(VersionSourceError):
                parse_resource_path(text)

    def test_official_fractional_numeric_cache_buster(self):
        url = RESOURCE_MAP_URL + "?46317.9367265972"
        self.assertEqual(validate_source(url), url)
        with self.assertRaises(VersionSourceError):
            validate_source(RESOURCE_MAP_URL + "? 46317.9367265972")
        with self.assertRaises(VersionSourceError):
            validate_source(RESOURCE_MAP_URL + "?46317.9367265972&other=1")
        called = []

        def opener(request, timeout):
            called.append(request.full_url)
            return FakeResponse(RESOURCE_MAP, request.full_url)

        with patch("wlre.services.official_version.time.time",
                   return_value=46317.9367265972):
            got = fetch_bytes(RESOURCE_MAP_URL, opener=opener)
        self.assertEqual(got, RESOURCE_MAP)
        self.assertEqual(called, [url])

    def test_no_sources_are_not_false_success(self):
        self.assertEqual(check_official_versions()["status"], "unverified")
        self.assertEqual(BASELINE, {"MainPackage": "1262", "DataPackage": "1262"})


if __name__ == "__main__":
    unittest.main()
