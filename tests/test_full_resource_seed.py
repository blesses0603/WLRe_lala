from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from wlre.paths import RESOURCE_ROOT
from wlre.storage.full_resource_seed import read_config
from wlre.storage.full_resource_seed import build_seed, verify_seed, SOURCE_MANIFEST, SEED_NAME
from wlre.storage.bundled_database import load_bundled_bytes


class FullResourceSeedTests(unittest.TestCase):
    def test_fresh_install_has_all_sources_without_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'empty_resources';root.mkdir()
            build_seed(RESOURCE_ROOT,root/SEED_NAME)
            db=base/'new_user.sqlite3'
            from wlre.storage.bundled_database import load_legacy_resource
            with self.assertRaises(FileNotFoundError):
                load_legacy_resource('npc_battle_talk_1262.json.gz',root=root,database=db)
            for name in SOURCE_MANIFEST:
                self.assertEqual(load_bundled_bytes(name,root=root,database=db),read_config(name, root=RESOURCE_ROOT))
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM bundled_active').fetchone()[0],13)
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
            self.assertEqual(load_bundled_bytes(name,root=root,database=db),read_config(name, root=RESOURCE_ROOT))
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM bundled_active').fetchone()[0],13)
                self.assertEqual(conn.execute('SELECT value FROM user_settings').fetchone()[0],'preserve')


class SourceRemovalTests(unittest.TestCase):
    def test_checkout_contains_complete_database_and_no_replaced_files(self):
        self.assertTrue(verify_seed(RESOURCE_ROOT / SEED_NAME))
        for name in SOURCE_MANIFEST:
            with self.subTest(name=name):
                self.assertFalse((RESOURCE_ROOT / name).exists())
                raw=read_config(name, root=RESOURCE_ROOT)
                import hashlib
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), SOURCE_MANIFEST[name])

    def test_missing_seed_does_not_silently_return_unverified_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'default_profile.json').write_bytes(b'{}')
            with self.assertRaises(FileNotFoundError):
                read_config('default_profile.json', root=root)

    def test_database_only_migration_and_read_only_audit(self):
        from wlre.storage.resource_migration import migrate_resources
        from tools.audit_all_resource_database import audit
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'user.sqlite3'
            self.assertEqual(migrate_resources(RESOURCE_ROOT,database),13)
            report=audit(database,RESOURCE_ROOT)
            self.assertTrue(report['all_identical'],report)
            self.assertEqual(report['summary']['identical'],13)

    def test_retired_bootstrap_resources_are_absent_from_seed_and_package(self):
        from wlre.storage.resource_seed_manifest import RETIRED_RESOURCES
        from wlre.resource_manifest import data_files
        with closing(sqlite3.connect(RESOURCE_ROOT / SEED_NAME)) as db:
            names={r[0] for r in db.execute('SELECT name FROM bundled_resources')}
        self.assertFalse(names & RETIRED_RESOURCES)
        self.assertFalse({p.name for p in data_files(RESOURCE_ROOT.parent)} & RETIRED_RESOURCES)
