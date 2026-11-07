from pathlib import Path
import hashlib
import sqlite3
import tempfile
import unittest
from wlre.paths import RESOURCE_ROOT
from wlre.storage.full_resource_seed import build_seed,verify_seed,provision_seed,read_config,SEED_NAME,SOURCE_MANIFEST
from wlre.storage.resource_seed_manifest import RETIRED_NAVIGATION,RETIRED_RESOURCES
from wlre.storage.bundled_database import load_bundled_bytes
from wlre.resource_manifest import data_files

class RetiredNavigationSeedTests(unittest.TestCase):
    def test_checkout_and_package_have_no_retired_sources(self):
        self.assertEqual(SOURCE_MANIFEST,{})
        self.assertFalse((RESOURCE_ROOT/SEED_NAME).exists())
        self.assertFalse(any((RESOURCE_ROOT/n).exists() for n in RETIRED_RESOURCES))
        self.assertFalse({p.name for p in data_files(RESOURCE_ROOT.parent,compact=True)} & RETIRED_RESOURCES)

    def test_old_apis_never_read_or_modify_existing_data(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);seed=root/SEED_NAME;seed.write_bytes(b'old user seed, preserve')
            user=root/'user.sqlite3';user.write_bytes(b'private data, preserve')
            before={p:p.read_bytes() for p in (seed,user)}
            for action in (lambda:verify_seed(seed),lambda:build_seed(root,seed),
                           lambda:provision_seed(seed,user),lambda:read_config('graph_origins.json',root=root)):
                with self.assertRaisesRegex(ValueError,'已退役'):action()
            self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_legacy_navigation_is_not_loaded_even_from_existing_valid_user_db(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);database=root/'user.sqlite3';raw=b'{}';digest=hashlib.sha256(raw).hexdigest()
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE bundled_active(name TEXT PRIMARY KEY,sha256 TEXT)')
                db.execute('CREATE TABLE bundled_resources(name TEXT,sha256 TEXT,data BLOB)')
                for name in RETIRED_NAVIGATION:
                    db.execute('INSERT INTO bundled_active VALUES (?,?)',(name,digest))
                    db.execute('INSERT INTO bundled_resources VALUES (?,?,?)',(name,digest,raw))
                    (root/name).write_bytes(raw)
            before=database.read_bytes()
            for name in RETIRED_NAVIGATION:
                with self.assertRaisesRegex(FileNotFoundError,'已退役'):
                    load_bundled_bytes(name,root=root,database=database)
                self.assertEqual((root/name).read_bytes(),raw)
            self.assertEqual(database.read_bytes(),before)

    def test_empty_current_install_migration_has_no_user_db_side_effect(self):
        from wlre.storage.resource_migration import migrate_resources
        with tempfile.TemporaryDirectory() as d:
            database=Path(d)/'user.sqlite3'
            self.assertEqual(migrate_resources(RESOURCE_ROOT,database),0)
            self.assertFalse(database.exists())
