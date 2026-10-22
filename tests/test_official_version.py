import io
import json
import unittest
from wlre.services.official_version import (
    RESOURCE_PATH_URL, VersionSourceError, check_official_versions,
    check_official_pc_versions, compare_versions, fetch_version,
    fetch_official_bytes, package_sources, parse_resource_path, parse_version,
    validate_source,
)

MAIN = package_sources("1.3.21")["MainPackage"]
DATA = package_sources("1.3.21")["DataPackage"]
MAPPING = b'[{"ExeVer":"1.1.3","DataVer":"1.3.21"},' \
          b'{"ExeVer":"1.1.4","DataVer":"1.3.21"},' \
          b'{"ExeVer":"1.2.0","DataVer":"1.3.21"},' \
          b'{"ExeVer":"1.3.0","DataVer":"1.3.21"}]'


class FakeResponse(io.BytesIO):
    def __init__(self, data, url=MAIN, status=200):
        super().__init__(data)
        self.url, self.status = url, status

    def geturl(self):
        return self.url


class OfficialVersionTests(unittest.TestCase):
    def test_exact_observed_endpoints(self):
        for url in [RESOURCE_PATH_URL, MAIN, DATA]:
            self.assertEqual(validate_source(url), url)
        for url in [
            "http://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat",
            "https://wlreftp.chinesegamer.net.evil.test/WLN/TW/ResourcePath_PC.dat",
            "https://wlreftp.chinesegamer.net@evil.test/WLN/TW/ResourcePath_PC.dat",
            "https://wlreftp.chinesegamer.net:443/WLN/TW/ResourcePath_PC.dat",
            "https://wlreftp.chinesegamer.net/WLN/TW/fake.version",
            "https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/evil.version",
            "https://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat?token=abc",
            "https://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat#frag",
            "https://wlreupload.chinesegamer.net/wln/TW/a.version",
        ]:
            with self.subTest(url=url), self.assertRaises(VersionSourceError):
                validate_source(url)

    def test_fiddler_resource_path_mapping(self):
        result = parse_resource_path(MAPPING)
        self.assertEqual(result["supported_exe_version"], "1.3.0")
        self.assertEqual(result["resource_path_version"], "1.3.21")
        self.assertFalse(result["client_path_changed"])
        self.assertEqual(package_sources(result["resource_path_version"]), {
            "MainPackage": MAIN, "DataPackage": DATA,
        })

    def test_updated_advertised_exe_path_not_stale(self):
        entries = json.loads(MAPPING)
        entries.append({"ExeVer": "1.3.1", "DataVer": "1.3.22"})
        mapping = parse_resource_path(json.dumps(entries).encode("utf-8"))
        self.assertEqual(mapping["latest_exe_version"], "1.3.1")
        self.assertEqual(mapping["resource_path_version"], "1.3.22")
        self.assertTrue(mapping["client_path_changed"])

    def test_bad_resource_path_payload_rejected(self):
        bad = [
            b'{}', b'[]',
            b'[{"ExeVer":"1.3.0","DataVer":"../../evil"}]',
            b'[{"ExeVer":"1.3.0","DataVer":"1.3.21"},{"ExeVer":"1.3.0","DataVer":"1.3.22"}]',
            b'[{"ExeVer":"1.3.1","DataVer":"1.3.22"}]',
            b'[{"ExeVer":"1.3.0","DataVer":"1.3.21","Url":"bad"}]',
        ]
        for entry in bad:
            with self.subTest(entry=entry), self.assertRaises(VersionSourceError):
                parse_resource_path(entry)

    def test_three_stage_official_1275_blocks(self):
        seen = []
        def get_mapping(url):
            seen.append(url)
            self.assertEqual(url, RESOURCE_PATH_URL)
            return MAPPING
        def get_version(url):
            seen.append(url)
            return {"MainPackage": "1275_2026_10_21_18_29_38_49",
                    "DataPackage": "1275_2026_10_21_18_27_33_84"}[
                        "MainPackage" if url == MAIN else "DataPackage"]
        result = check_official_pc_versions(
            path_fetcher=get_mapping, version_fetcher=get_version)
        self.assertEqual(result["status"], "resources_changed")
        self.assertEqual(seen, [RESOURCE_PATH_URL, MAIN, DATA])
        self.assertEqual(result["packages"]["MainPackage"]["comparison"], "newer")

    def test_changed_resource_path_blocks_even_if_package_fails(self):
        entries = json.loads(MAPPING)
        entries.append({"ExeVer": "1.3.1", "DataVer": "1.3.22"})
        result = check_official_pc_versions(
            path_fetcher=lambda _: json.dumps(entries).encode(),
            version_fetcher=lambda _: (_ for _ in ()).throw(VersionSourceError("offline")))
        self.assertEqual(result["status"], "resources_changed")
        self.assertEqual(result["resource_path"]["resource_path_version"], "1.3.22")

    def test_invalid_mapping_never_falls_back_to_old_path(self):
        result = check_official_pc_versions(
            path_fetcher=lambda _: b"not json",
            version_fetcher=lambda _: self.fail("must not fetch any package"))
        self.assertEqual(result["status"], "unverified")
        self.assertIsNone(result["resource_path"])

    def test_bounded_uncached_https_get(self):
        def opener(request, *, timeout):
            self.assertEqual(request.full_url.split("?", 1)[0], MAIN)
            self.assertIn("_ts=123", request.full_url)
            self.assertIn("no-cache", request.headers.get("Cache-control", ""))
            return FakeResponse(b"1275_2026_10_21_18_29_38_49", url=request.full_url)
        self.assertEqual(
            parse_version(fetch_official_bytes(MAIN, opener=opener, nonce=123)),
            "1275_2026_10_21_18_29_38_49")
        with self.assertRaises(VersionSourceError):
            fetch_official_bytes(MAIN, opener=lambda *a, **kw:
                                 FakeResponse(b"1275", url="https://evil.example/a"))
        with self.assertRaises(VersionSourceError):
            fetch_official_bytes(MAIN, opener=lambda *a, **kw:
                                 FakeResponse(b"x" * 4097))
        with self.assertRaises(VersionSourceError):
            fetch_official_bytes(MAIN, opener=lambda *a, **kw:
                                 FakeResponse(b"1275", status=404))

    def test_version_compare(self):
        self.assertEqual(compare_versions("1262", "1262"), "same")
        self.assertEqual(compare_versions("1262", "1275_2026_10_21_18_29_38_49"), "newer")
        self.assertEqual(compare_versions("1262", "1261"), "older")
        with self.assertRaises(VersionSourceError):
            parse_version(b"<html>bad</html>")

    def test_partial_failure_never_claims_same(self):
        self.assertEqual(check_official_versions({"MainPackage": MAIN},
                         fetcher=lambda _: "1262")["status"], "unverified")
        self.assertEqual(check_official_versions({"MainPackage": MAIN, "DataPackage": DATA},
                         fetcher=lambda _: "1262")["status"], "same_resources")


if __name__ == "__main__":
    unittest.main()
