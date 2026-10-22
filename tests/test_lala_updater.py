"""GitHub official Release only, no install, no external network test."""
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from wlre.services import lala_updater as lu


def make_zip(*, malicious=False):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("WLRe_LaLa/WLRe_LaLa.exe", b"test-not-an-exe")
        if malicious:
            z.writestr("../evil.txt", b"escape")
    return b.getvalue()


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)


def release_payload(tag="v0.6.0"):
    main = f"WLRe_LaLa_{tag}_windows_x64.zip"
    return {
        "tag_name": tag, "draft": False, "prerelease": False,
        "assets": [
            {"name": name, "browser_download_url":
             f"https://github.com/{lu.REPO}/releases/download/{tag}/{name}"}
            for name in (main, "SHA256SUMS.txt")
        ],
    }


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.p1 = patch("wlre.services.lala_updater.platform.system", return_value="Windows")
        self.p2 = patch("wlre.services.lala_updater.platform.machine", return_value="AMD64")
        self.p1.start()
        self.p2.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.p2.stop)

    def fake_opener(self, *, tag="v0.6.0", bad_sha=False, malicious=False, missing=False):
        payload = release_payload(tag)
        if missing:
            payload["assets"] = []
        archive = make_zip(malicious=malicious)
        name = f"WLRe_LaLa_{tag}_windows_x64.zip"
        hexdigest = "0"*64 if bad_sha else hashlib.sha256(archive).hexdigest()
        content = {
            lu.API: json.dumps(payload).encode(),
            f"https://github.com/{lu.REPO}/releases/download/{tag}/SHA256SUMS.txt":
                f"{hexdigest}  {name}\n".encode(),
            f"https://github.com/{lu.REPO}/releases/download/{tag}/{name}": archive,
        }
        def opener(request, *, timeout):
            return Response(content[request.full_url])
        return opener

    def test_reject_downgrade_and_dev_version(self):
        output = lu.check_lala_release(current_version="0.5.17",
                                       opener=self.fake_opener(tag="v0.5.0"))
        self.assertEqual(output["status"], "up_to_date")
        self.assertEqual(output["published"], "v0.5.0")

    def test_new_official_release_detected(self):
        output = lu.check_lala_release(current_version="0.5.17",
                                       opener=self.fake_opener())
        self.assertEqual(output["status"], "update_available")
        self.assertEqual(output["published"], "v0.6.0")
        self.assertIn("windows_x64.zip", output["archive_name"])

    def test_missing_assets_cannot_offer_download(self):
        with self.assertRaises(lu.UpdateError):
            lu.check_lala_release(opener=self.fake_opener(missing=True))

    def test_verified_zip_download_and_staging(self):
        opener = self.fake_opener()
        info = lu.check_lala_release(opener=opener)
        with tempfile.TemporaryDirectory() as tmp:
            target = lu.download_verified_release(info, directory=tmp, opener=opener)
            self.assertTrue(target.is_file())
            self.assertFalse((Path(tmp) / (target.name + ".partial")).exists())
            with zipfile.ZipFile(target) as z:
                self.assertIn("WLRe_LaLa/WLRe_LaLa.exe", z.namelist())

    def test_bad_sha_never_overwrites_prior_archive(self):
        good = self.fake_opener()
        bad = self.fake_opener(bad_sha=True)
        info = lu.check_lala_release(opener=good)
        with tempfile.TemporaryDirectory() as tmp:
            old = lu.download_verified_release(info, directory=tmp, opener=good)
            original = old.read_bytes()
            with self.assertRaises(lu.UpdateError):
                lu.download_verified_release(info, directory=tmp, opener=bad)
            self.assertEqual(old.read_bytes(), original)
            self.assertFalse((Path(tmp) / (old.name + ".partial")).exists())

    def test_malicious_zip_rejected(self):
        opener = self.fake_opener(malicious=True)
        info = lu.check_lala_release(opener=opener)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(lu.UpdateError):
                lu.download_verified_release(info, directory=tmp, opener=opener)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_untrusted_asset_url_rejected(self):
        info = lu.check_lala_release(opener=self.fake_opener())
        info["archive_url"] = "https://evil.example/update.zip"
        with self.assertRaises(lu.UpdateError):
            lu.download_verified_release(info)

    def test_update_version_strict(self):
        with self.assertRaises(lu.UpdateError):
            lu.parsed_version("v0.6.0-alpha")
        with self.assertRaises(lu.UpdateError):
            lu.target_archive("not-a-version")


if __name__ == "__main__":
    unittest.main()
