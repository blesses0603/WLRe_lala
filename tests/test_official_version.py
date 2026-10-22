"""Offline tests based on the user's observed Fiddler PC requests."""
import io
import unittest

from wlre.services.official_version import (
    BASELINE, BASELINE_MANIFEST, RESOURCE_MAP_URL, VersionSourceError,
    check_official_game_resources, check_official_versions, compare_versions,
    fetch_bytes, fetch_version, official_package_urls,
    parse_resource_path, parse_version, validate_source,
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

    def test_no_sources_are_not_false_success(self):
        self.assertEqual(check_official_versions()["status"], "unverified")
        self.assertEqual(BASELINE, {"MainPackage": "1262", "DataPackage": "1262"})


if __name__ == "__main__":
    unittest.main()
