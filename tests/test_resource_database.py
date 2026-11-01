import sqlite3
import json
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch
from pathlib import Path

from wlre.services.world.resource_database import record_inventory


class ResourceDatabaseTests(unittest.TestCase):
    def test_historical_candidate_table_is_preserved_but_not_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE candidate_rows (version_id INTEGER, source TEXT, row_key TEXT, data TEXT)')
                db.execute("INSERT INTO candidate_rows VALUES (1, 'legacy', 'a', 'historical')")
            record_inventory(path, 'a' * 64, {'tables/ItemData_C.bytes': b'bad'})
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT data FROM candidate_rows').fetchone()[0], 'historical')
                self.assertIn('parsed_resource_rows', {row[0] for row in db.execute('SELECT name FROM sqlite_master')})

    def test_new_database_never_creates_candidate_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            record_inventory(path, 'b' * 64, {'tables/ItemData_C.bytes': b'bad'})
            with closing(sqlite3.connect(path)) as db:
                self.assertNotIn('candidate_rows', {row[0] for row in db.execute('SELECT name FROM sqlite_master')})

    def test_active_identity_is_bound_to_database_catalog_key(self):
        from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
        from wlre.services.world.resource_database import read_active_database_identity
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            identity = OfficialCatalogIdentity('1.3.22.1', '1.3.0', (
                PackageRevision('DataPackage', '1286_2026_10_29_13_42_37_94', 'a'*64, 'a'*8),
                PackageRevision('MainPackage', '1284_2026_10_28_19_50_04_11', 'b'*64, 'b'*8)))
            record_inventory(path, identity.key, {'tables/a/A.bytes': b'content'}, identity=identity)
            self.assertEqual(read_active_database_identity(path), identity.as_dict())
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE version_identities SET identity='{}'")
            self.assertIsNone(read_active_database_identity(path))
    def test_recipe_reader_keeps_duplicate_outputs_and_requires_same_version_items(self):
        from wlre.services.world.resource_database import read_catalog_tables
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            key = 'a' * 64
            rows = [{'item_id': 7, 'candidate_row_key': 1, 'time_id': 0, 'materials': [{'item_id': 8}]},
                    {'item_id': 7, 'candidate_row_key': 2, 'time_id': 0, 'materials': [{'item_id': 8}]}]
            with patch('wlre.services.world.smith_candidate.parse_smith_candidate', return_value=rows), \
                 patch('wlre.services.world.itemdata_v1.parse_itemdata', return_value={7: {'name': 'a'}, 8: {'name': 'b'}}):
                record_inventory(path, key, {'tables/a/SmithData_C.bytes': b'smith',
                                             'tables/a/ItemData_C.bytes': b'items'})
                self.assertEqual(len(read_catalog_tables(path, key, ['recipes'])['recipes']), 2)
            with patch('wlre.services.world.smith_candidate.parse_smith_candidate', return_value=rows), \
                 patch('wlre.services.world.itemdata_v1.parse_itemdata', return_value={7: {'name': 'a'}}):
                with self.assertRaises(ValueError):
                    read_catalog_tables(path, key, ['recipes'])

    def test_expedition_requires_all_five_tables_in_one_catalog(self):
        from wlre.services.world.resource_database import read_catalog_tables
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            key = 'a' * 64
            tables = {f'tables/a/{name}.bytes': name.encode() for name in
                      ('AdventureData_C', 'AdventureLvData_C', 'NpcData_C', 'NpcCareerData_C', 'TextData_C')}
            with patch('wlre.services.expedition.data.parse_catalog', return_value={'tasks': {}, 'levels': {}}), \
                 patch('wlre.services.expedition.data.attach_names', side_effect=lambda catalog, raw: catalog), \
                 patch('wlre.services.expedition.data.parse_npcs', return_value={1: {'id': 1}}), \
                 patch('wlre.services.expedition.data.parse_text_data', return_value={}):
                record_inventory(path, key, tables)
                result = read_catalog_tables(path, key, ['expedition'])
                self.assertIn(1, result['expedition']['npcs'])
                with self.assertRaises(ValueError):
                    read_catalog_tables(path, 'b' * 64, ['expedition'])

    def test_catalog_reader_requires_one_version_and_valid_source_hashes(self):
        from wlre.services.world.resource_database import read_catalog_tables
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            key = 'a' * 64
            with patch('wlre.services.world.itemdata_v1.parse_itemdata', return_value={7: {'name': '測試'}}), \
                 patch('wlre.services.world.npc_talk.parse_talk_data', return_value={3: {'text': '對話'}}):
                record_inventory(path, key, {'tables/a/ItemData_C.bytes': b'items',
                                             'tables/a/TalkData_C.bytes': b'talk'})
                result = read_catalog_tables(path, key, ['items', 'talks'])
                self.assertEqual(result['items'][7]['name'], '測試')
                self.assertEqual(result['talks'][3]['text'], '對話')
                with self.assertRaises(ValueError):
                    read_catalog_tables(path, 'b' * 64, ['items', 'talks'])
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute("UPDATE resources SET data=? WHERE name='TalkData_C.bytes'", (b'bad',))
                with self.assertRaises(ValueError):
                    read_catalog_tables(path, key, ['items', 'talks'])

    def test_one_invalid_table_does_not_prevent_other_table_from_indexing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            payloads = {'tables/a/TalkData_C.bytes': b'bad',
                        'tables/a/ScenesData_C.bytes': b'valid'}
            with patch('wlre.services.world.npc_talk.parse_talk_data', side_effect=ValueError('invalid')), \
                 patch('wlre.services.instance_catalog.parse_stages', return_value={1: {'name': 'scene'}}):
                result = record_inventory(path, 'one', payloads)
            self.assertEqual(result['other_rows']['talk_v1']['status'], 'parse_failed')
            self.assertEqual(result['other_rows']['scenes_v1']['status'], 'parsed')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM resources').fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT count(*) FROM parsed_resource_rows WHERE source='scenes_v1'").fetchone()[0], 1)

    def test_eve_comparison_uses_scene_and_event_index(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            def derive(raw, source):
                scenes = {'1': [{'index': 2, 'value': raw.decode()}]}
                if raw == b'new':
                    scenes['2'] = [{'index': 2, 'value': 'new'}]
                return json.dumps({'scenes': scenes}).encode()
            with patch('wlre.services.world.eve_v115.derive_eve_index', side_effect=derive):
                record_inventory(path, 'old', {'tables/a/Eve.bytes': b'old'})
                diff = record_inventory(path, 'new', {'tables/a/Eve.bytes': b'new'})
            self.assertEqual(diff['other_rows']['eve_npc_v1']['changed'], ['1:2'])
            self.assertEqual(diff['other_rows']['eve_npc_v1']['added'], ['2:2'])

    def test_talk_rows_are_compared_and_prior_decode_failure_is_not_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            with patch('wlre.services.world.npc_talk.parse_talk_data',
                       side_effect=lambda raw: {b'old': {1: {'text': 'a'}},
                                                b'new': {1: {'text': 'b'}, 2: {'text': 'c'}}}[raw]):
                record_inventory(path, 'old', {'tables/a/TalkData_C.bytes': b'old'})
                result = record_inventory(path, 'new', {'tables/a/TalkData_C.bytes': b'new'})
            self.assertEqual(result['other_rows']['talk_v1']['changed'], ['1'])
            self.assertEqual(result['other_rows']['talk_v1']['added'], ['2'])

    def test_same_identity_is_immutable_and_rollback_compares_active_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            def payload(value):
                return {'tables/a/A.bytes': value}
            record_inventory(path, 'one', payload(b'one'))
            record_inventory(path, 'two', payload(b'two'))
            with self.assertRaises(ValueError):
                record_inventory(path, 'two', payload(b'bad'))
            rollback = record_inventory(path, 'one', payload(b'one'))
            self.assertEqual(rollback['changed'], ['A.bytes'])
            self.assertEqual(record_inventory(path, 'one', payload(b'one'))['changed'], ['A.bytes'])

    def test_raw_item_data_requires_matching_version_identity(self):
        from wlre.services.world.resource_database import read_catalog_tables
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            record_inventory(path, 'a' * 64, {'tables/a/ItemData_C.bytes': b'table'})
            with self.assertRaises(ValueError):
                read_catalog_tables(path, 'b' * 64, ['items'])

    def test_item_rows_are_versioned_and_compared(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            with patch('wlre.services.world.itemdata_v1.parse_itemdata', side_effect=lambda raw: {
                b'old': {1: {'name': 'old'}, 2: {'name': 'same'}},
                b'new': {1: {'name': 'new'}, 3: {'name': 'added'}}}[raw]):
                record_inventory(path, 'old', {'tables/a/ItemData_C.bytes': b'old'})
                diff = record_inventory(path, 'new', {'tables/a/ItemData_C.bytes': b'new'})['item_rows']
            self.assertEqual(diff['added'], ['3'])
            self.assertEqual(diff['changed'], ['1'])
            self.assertEqual(diff['removed'], ['2'])

    def test_legacy_candidate_indexes_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            result = record_inventory(path, 'one', {
                'tables/a/SmithData_C.bytes': b'table',
                'candidate_indexes/smith_recipes_1286.json': b'invalid legacy payload',
            })
            self.assertIsNone(result['smith_rows'])
            with closing(sqlite3.connect(path)) as db, db:
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='candidate_rows'").fetchone())

    def test_records_versions_and_compares_table_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.sqlite3'
            record_inventory(path, 'old', {'tables/a/A.bytes': b'old', 'tables/a/B.bytes': b'same'})
            diff = record_inventory(path, 'new', {'tables/b/A.bytes': b'new', 'tables/b/C.bytes': b'added'})
            self.assertEqual(diff['changed'], ['A.bytes'])
            self.assertEqual(diff['added'], ['C.bytes'])
            self.assertEqual(diff['missing_from_current'], ['B.bytes'])
            record_inventory(path, 'new', {'tables/b/A.bytes': b'new', 'tables/b/C.bytes': b'added'})
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM resources').fetchone()[0], 4)
                self.assertEqual(db.execute('SELECT data FROM resources JOIN versions ON versions.id=resources.version_id WHERE catalog_key=? AND name=?', ('new', 'A.bytes')).fetchone()[0], b'new')
