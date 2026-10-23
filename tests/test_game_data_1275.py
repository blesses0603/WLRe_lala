"""Fixture-only tests: CI does not require proprietary game data binaries."""
import hashlib
import tempfile
import unittest
import warnings
from pathlib import Path
from zipfile import ZipFile

from wlre.services.world.game_data_1275 import read_manifest, verify_archive, _valid_manifest, read_table


class Full1275ManifestTests(unittest.TestCase):
    def test_unpinned_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'malformed.zip'
            with ZipFile(path,'w') as z:z.writestr('manifest.json','{}')
            with self.assertRaises(ValueError):verify_archive(path)

    def test_duplicate_members_rejected_before_use(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'duplicate.zip'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                with ZipFile(path,'w') as z:
                    z.writestr('manifest.json',b'{}')
                    z.writestr('manifest.json',b'{}')
            with self.assertRaises(ValueError):verify_archive(path)

    def test_incomplete_table_manifest_rejected(self):
        with self.assertRaises(ValueError):
            _valid_manifest({'schema_version':1, 'official_resource_revision':1275,
                             'base_resource_revision':1262, 'files':{},
                             'changed_bundles':[], 'new_main_assets':[]})

    def test_nonmatching_manifest_sha_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fake.zip'
            with ZipFile(path,'w') as z:z.writestr('manifest.json',b'{"hello":1}')
            with ZipFile(path) as z:
                with self.assertRaises(ValueError):read_manifest(z)

    def test_read_table_rejects_traversal(self):
        with self.assertRaises(ValueError):
            read_table('never-exists.zip','../../DailyTaskData_C')


if __name__=='__main__': unittest.main()
