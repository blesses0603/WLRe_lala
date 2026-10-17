import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.build.release_nuitka import package_release, validate_tag
from wlre import __version__


class NuitkaReleaseTests(unittest.TestCase):
    def test_tag_must_match_application_version(self):
        self.assertEqual(validate_tag('v' + __version__), 'v' + __version__)
        for tag in ('main', __version__, 'v99.0.0', 'v' + __version__ + '-test'):
            with self.assertRaises(ValueError):
                validate_tag(tag)

    def make_build(self, root):
        source = root / 'dist_nuitka/standalone/WLRe_LaLa.dist'
        source.mkdir(parents=True)
        (source / 'WLRe_LaLa.exe').write_bytes(b'fixture exe')
        (source / 'runtime.dll').write_bytes(b'fixture runtime')
        (source / 'wlre/resources').mkdir(parents=True)
        (source / 'wlre/resources/fixture.zip').write_bytes(b'fixture resource')
        return source

    def test_zip_includes_whole_distribution_and_matching_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_build(root)
            archive, checksum = package_release('v' + __version__, root)
            with zipfile.ZipFile(archive) as bundle:
                self.assertIsNone(bundle.testzip())
                self.assertEqual(set(bundle.namelist()), {
                    'WLRe_LaLa/WLRe_LaLa.exe', 'WLRe_LaLa/runtime.dll',
                    'WLRe_LaLa/wlre/resources/fixture.zip'})
                self.assertEqual(bundle.read('WLRe_LaLa/runtime.dll'), b'fixture runtime')
            self.assertEqual(checksum.read_text(),
                hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
            self.assertFalse(archive.with_suffix('.zip.tmp').exists())

    def test_missing_or_empty_exe_cannot_be_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                package_release('v' + __version__, root)
            source = self.make_build(root)
            (source / 'WLRe_LaLa.exe').write_bytes(b'')
            with self.assertRaises(ValueError):
                package_release('v' + __version__, root)
            self.assertFalse((root / 'dist_nuitka/release').exists())

    def test_failed_crc_does_not_replace_previous_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_build(root)
            archive, checksum = package_release('v' + __version__, root)
            previous = archive.read_bytes(), checksum.read_bytes()
            with patch.object(zipfile.ZipFile, 'testzip', return_value='runtime.dll'):
                with self.assertRaises(ValueError):
                    package_release('v' + __version__, root)
            self.assertEqual((archive.read_bytes(), checksum.read_bytes()), previous)
            self.assertFalse(archive.with_suffix('.zip.tmp').exists())
