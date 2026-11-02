"""Database bytes must match the exact independently verified official runtime."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from wlre.services.world.bundle_runtime_1275 import _REQUIRED_TABLES
from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
from wlre.services.world.resource_database import database_matches_runtime


class DatabaseLoginMatchTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'catalog.sqlite3'
        identity=OfficialCatalogIdentity('1.3.22.1','1.3.0',(
            PackageRevision('DataPackage','1286_full','a'*64,'a'*8),
            PackageRevision('MainPackage','1284_full','b'*64,'b'*8)))
        self.raw={name:name.encode() for name in _REQUIRED_TABLES}
        self.runtime=SimpleNamespace(catalog_identity=identity,
            source_sha256={name:hashlib.sha256(raw).hexdigest() for name,raw in self.raw.items()})
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE versions (id INTEGER PRIMARY KEY,catalog_key TEXT)')
            db.execute('CREATE TABLE version_identities (version_id INTEGER PRIMARY KEY,identity TEXT)')
            db.execute('CREATE TABLE sync_state (singleton INTEGER PRIMARY KEY,active_id INTEGER)')
            db.execute('CREATE TABLE resources (version_id INTEGER,name TEXT,sha256 TEXT,data BLOB)')
            db.execute('INSERT INTO versions VALUES (1,?)',(identity.key,))
            db.execute('INSERT INTO version_identities VALUES (1,?)',
                       (json.dumps(identity.as_dict(),ensure_ascii=True,sort_keys=True,separators=(',',':')),))
            db.execute('INSERT INTO sync_state VALUES (1,1)')
            db.executemany('INSERT INTO resources VALUES (1,?,?,?)',
                          ((name+'.bytes',self.runtime.source_sha256[name],raw) for name,raw in self.raw.items()))

    def test_full_match_is_read_only(self):
        before=self.path.read_bytes()
        self.assertTrue(database_matches_runtime(self.path,self.runtime))
        self.assertEqual(self.path.read_bytes(),before)

    def test_rehashed_corruption_is_rejected_against_official_runtime(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE resources SET data=?,sha256=? WHERE name=?',
                       (b'changed',hashlib.sha256(b'changed').hexdigest(),'ItemData_C.bytes'))
        self.assertFalse(database_matches_runtime(self.path,self.runtime))

    def test_missing_required_source_is_rejected(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("DELETE FROM resources WHERE name='SmithData_C.bytes'")
        self.assertFalse(database_matches_runtime(self.path,self.runtime))

    def test_identical_versions_with_republished_manifest_are_not_equal(self):
        from dataclasses import replace
        old=self.runtime.catalog_identity
        self.runtime.catalog_identity=replace(old,packages=(
            replace(old.packages[0],manifest_sha256='c'*64),old.packages[1]))
        self.assertFalse(database_matches_runtime(self.path,self.runtime))

    def test_missing_or_invalid_database_and_empty_source_proof_are_rejected(self):
        self.assertFalse(database_matches_runtime(self.path.with_name('missing.sqlite3'),self.runtime))
        self.runtime.source_sha256={}
        self.assertFalse(database_matches_runtime(self.path,self.runtime))
        self.path.write_bytes(b'not sqlite')
        self.assertFalse(database_matches_runtime(self.path,self.runtime))
