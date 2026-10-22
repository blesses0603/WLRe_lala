import io
import unittest

from wlre.services.official_version import (
    VersionSourceError, check_official_versions, compare_versions,
    fetch_version, parse_version, validate_source,
)

MAIN = "https://wlreupload.chinesegamer.net/wln/TW/PC/PackageManifest_MainPackage.version"
DATA = "https://wlreupload.chinesegamer.net/wln/TW/PC/PackageManifest_DataPackage.version"


class FakeResponse(io.BytesIO):
    def __init__(self, data, url=MAIN):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


class VersionTests(unittest.TestCase):
    def test_official_source_only(self):
        validate_source(MAIN)
        for url in (
            "http://wlreupload.chinesegamer.net/wln/TW/a.version",
            "https://example.com/wln/TW/a.version",
            "https://wlreupload.chinesegamer.net.evil.com/wln/TW/a.version",
            "https://wlreupload.chinesegamer.net@evil.com/wln/TW/a.version",
            "https://wlreupload.chinesegamer.net:443/wln/TW/a.version",
            "https://wlreupload.chinesegamer.net/private/a.version",
            "https://wlreupload.chinesegamer.net/wln/TW/a.version?token=foo",
        ):
            with self.subTest(url=url), self.assertRaises(VersionSourceError):
                validate_source(url)

    def test_version_formats(self):
        self.assertEqual(parse_version(b"1262\n"), "1262")
        self.assertEqual(parse_version(b'{"packageVersion":"1263"}'), "1263")
        self.assertEqual(parse_version(b'{"PackageVersion":"1264"}'), "1264")
        with self.assertRaises(VersionSourceError):
            parse_version(b"<html>not a version</html>")
        with self.assertRaises(VersionSourceError):
            parse_version(b'{"some_unrelated_key":123}')

    def test_fetch_read_and_redirect_guard(self):
        self.assertEqual(fetch_version(MAIN, opener=lambda *a, **kw: FakeResponse(b"1262")), "1262")
        with self.assertRaises(VersionSourceError):
            fetch_version(MAIN, opener=lambda *a, **kw: FakeResponse(b"1262", "https://evil.example/a.version"))
        with self.assertRaises(VersionSourceError):
            fetch_version(MAIN, opener=lambda *a, **kw: FakeResponse(b"a" * 4097))

    def test_numeric_and_opaque_versions(self):
        self.assertEqual(compare_versions("1262", "1262"), "same")
        self.assertEqual(compare_versions("1262", "1263"), "newer")
        self.assertEqual(compare_versions("1262", "1261"), "older")
        self.assertEqual(compare_versions("1262", "2026-10-22"), "different")

    def test_unverified_default_and_partial(self):
        self.assertEqual(check_official_versions()["status"], "unverified")
        self.assertEqual(check_official_versions({"MainPackage": MAIN}, fetcher=lambda u: "1262")["status"], "unverified")

    def test_both_packages_required_and_failure_unknown(self):
        sources = {"MainPackage": MAIN, "DataPackage": DATA}
        self.assertEqual(check_official_versions(sources, fetcher=lambda u: "1262")["status"], "same_resources")
        self.assertEqual(check_official_versions(sources, fetcher=lambda u: "1263" if u == DATA else "1262")["status"], "resources_changed")
        def broken(url):
            if url == DATA:
                raise VersionSourceError("bad")
            return "1263"
        self.assertEqual(check_official_versions(sources, fetcher=broken)["status"], "unverified")
        self.assertEqual(check_official_versions(sources, fetcher=lambda u: "1262")["protocol_compatibility"], "unverified")


if __name__ == "__main__":
    unittest.main()
