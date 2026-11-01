from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from wlre.paths import RESOURCE_ROOT
from wlre.storage.full_resource_seed import build_seed, verify_seed, SOURCE_MANIFEST, SEED_NAME
from wlre.storage.bundled_database import load_bundled_bytes


class FullResourceSeedTests(unittest.TestCase):
    def test_fresh_install_has_all_sources_without_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'empty_resources';root.mkdir()
            build_seed(RESOURCE_ROOT,root/SEED_NAME)
            db=base/'new_user.sqlite3'
            for name in SOURCE_MANIFEST:
                self.assertEqual(load_bundled_bytes(name,root=root,database=db),(RESOURCE_ROOT/name).read_bytes())
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM bundled_active').fetchone()[0],27)
            self.assertEqual(list(root.iterdir()),[root/SEED_NAME])

    def test_modified_blob_and_self_computed_hash_cannot_replace_reviewed_source(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            seed=build_seed(RESOURCE_ROOT,Path(directory)/SEED_NAME)
            name=next(iter(SOURCE_MANIFEST));raw=b'tampered';digest=hashlib.sha256(raw).hexdigest()
            with closing(sqlite3.connect(seed)) as db, db:
                db.execute('INSERT INTO bundled_resources VALUES (?,?,?)',(name,digest,raw))
                db.execute('UPDATE bundled_active SET sha256=? WHERE name=?',(digest,name))
            with self.assertRaises(ValueError): verify_seed(seed)

    def test_existing_partial_database_is_completed_from_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);seed=build_seed(RESOURCE_ROOT,root/SEED_NAME)
            db=root/'user.sqlite3'
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute('CREATE TABLE user_settings (value TEXT)')
                conn.execute("INSERT INTO user_settings VALUES ('preserve')")
            name=next(iter(SOURCE_MANIFEST))
            self.assertEqual(load_bundled_bytes(name,root=root,database=db),(RESOURCE_ROOT/name).read_bytes())
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM bundled_active').fetchone()[0],27)
                self.assertEqual(conn.execute('SELECT value FROM user_settings').fetchone()[0],'preserve')
