"""Versioned local inventory of extracted official resources.

This stores raw tables and records whole-file changes. It does not assert
gameplay compatibility or replace the reviewed runtime.
"""
import hashlib
import sqlite3
import json
from contextlib import closing
from pathlib import PurePosixPath


def record_inventory(path, catalog_key, payloads, *, identity=None):
    tables = {}
    for member, data in payloads.items():
        if not member.startswith('tables/') or not member.endswith('.bytes'):
            continue
        name = PurePosixPath(member).name
        if name in tables or not isinstance(data, bytes):
            raise ValueError('Ambiguous or invalid resource table')
        tables[name] = data
    if not tables:
        raise ValueError('No resource tables to record')
    identity_json = None
    if identity is not None:
        from wlre.services.world.catalog_identity import OfficialCatalogIdentity
        if not isinstance(identity, OfficialCatalogIdentity) or identity.key != catalog_key:
            raise ValueError('Catalog identity does not match inventory')
        identity_json = json.dumps(identity.as_dict(), ensure_ascii=True, sort_keys=True,
                                   separators=(',', ':'))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS versions (id INTEGER PRIMARY KEY, catalog_key TEXT UNIQUE NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS version_identities (version_id INTEGER PRIMARY KEY, identity TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS resources (version_id INTEGER NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(version_id,name))')
        db.execute('CREATE TABLE IF NOT EXISTS parsed_resource_rows (version_id INTEGER NOT NULL, source TEXT NOT NULL, row_key TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(version_id,source,row_key))')
        db.execute('CREATE TABLE IF NOT EXISTS sync_state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_id INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS version_parents (version_id INTEGER PRIMARY KEY, parent_id INTEGER)')
        if 'previous_id' not in {row[1] for row in db.execute('PRAGMA table_info(sync_state)')}:
            db.execute('ALTER TABLE sync_state ADD COLUMN previous_id INTEGER')
        db.execute('INSERT OR IGNORE INTO versions(catalog_key) VALUES (?)', (catalog_key,))
        current = db.execute('SELECT id FROM versions WHERE catalog_key = ?', (catalog_key,)).fetchone()[0]
        if identity_json is not None:
            stored = db.execute('SELECT identity FROM version_identities WHERE version_id=?', (current,)).fetchone()
            if stored and stored[0] != identity_json:
                raise ValueError('Catalog identity changed for the same catalog key')
            db.execute('INSERT OR IGNORE INTO version_identities VALUES (?, ?)', (current, identity_json))
        active = db.execute('SELECT active_id, previous_id FROM sync_state WHERE singleton=1').fetchone()
        parent = db.execute('SELECT parent_id FROM version_parents WHERE version_id=?', (current,)).fetchone()
        if active and active[0] != current:
            previous = (active[0],)
            db.execute('INSERT OR IGNORE INTO version_parents VALUES (?, ?)', (current, active[0]))
        else:
            prior_id = active[1] if active and active[1] is not None else (parent[0] if parent else None)
            previous = (prior_id,) if prior_id is not None and prior_id != current else None
        db.execute('INSERT OR REPLACE INTO sync_state(singleton,active_id,previous_id) VALUES (1, ?, ?)',
                   (current, previous[0] if previous else None))
        prior = dict(db.execute('SELECT name, sha256 FROM resources WHERE version_id = ?', (previous[0],))) if previous else {}
        existing = dict(db.execute('SELECT name, sha256 FROM resources WHERE version_id = ?', (current,)))
        digests = {name: hashlib.sha256(data).hexdigest() for name, data in tables.items()}
        for name, data in tables.items():
            if existing.get(name) == digests[name]:
                continue
            if name in existing:
                raise ValueError('Resource changed for the same catalog identity')
            db.execute('INSERT INTO resources VALUES (?, ?, ?, ?) '
                       'ON CONFLICT(version_id,name) DO UPDATE SET sha256=excluded.sha256, data=excluded.data',
                       (current, name, digests[name], data))
        # Persist only derived rows from verified official raw tables.
        row_changes = None
        legacy_recipe_changes = None
        item_changes = None
        item_raw = tables.get('ItemData_C.bytes')
        if item_raw is not None:
            from wlre.services.world.itemdata_v1 import parse_itemdata
            def item_rows(raw):
                return {str(k): json.dumps(v, ensure_ascii=True, sort_keys=True,
                                            separators=(',', ':'))
                        for k, v in parse_itemdata(raw).items()}
            try:
                new_items = item_rows(item_raw)
                previous_raw = (db.execute('SELECT data FROM resources WHERE version_id=? AND name=?',
                                           (previous[0], 'ItemData_C.bytes')).fetchone()
                                if previous else None)
                old_items = {}
                previous_status = 'unavailable'
                if previous_raw:
                    try:
                        old_items = item_rows(previous_raw[0])
                        previous_status = 'parsed'
                    except ValueError:
                        previous_status = 'parse_failed'
                old_saved = dict(db.execute('SELECT row_key,data FROM parsed_resource_rows WHERE version_id=? AND source=?', (current, 'items_v1')))
                if old_saved and old_saved != new_items:
                    raise RuntimeError('Item rows changed for the same catalog identity')
                if not old_saved:
                    db.executemany('INSERT INTO parsed_resource_rows VALUES (?, ?, ?, ?)',
                                   ((current, 'items_v1', k, v) for k, v in new_items.items()))
                item_changes = {'status': 'parsed', 'count': len(new_items),
                                'previous_available': previous_status == 'parsed',
                                'previous_status': previous_status,
                                'added': sorted(new_items.keys() - old_items.keys()) if previous_status == 'parsed' else [],
                                'changed': sorted(k for k in new_items.keys() & old_items.keys() if new_items[k] != old_items[k]),
                                'removed': sorted(old_items.keys() - new_items.keys())}
            except ValueError:
                item_changes = {'status': 'parse_failed'}
        smith_raw=tables.get('SmithData_C.bytes')
        if smith_raw is not None:
            from wlre.services.world.smith_candidate import parse_smith_records
            def smith_rows(raw):
                rows=parse_smith_records(raw)
                return {str(row.get('recipe_id',row.get('candidate_row_key',row['item_id']))):
                        json.dumps(row,ensure_ascii=True,sort_keys=True,separators=(',',':'))
                        for row in rows}
            try:
                new_rows=smith_rows(smith_raw)
            except (ValueError,TypeError,KeyError,OverflowError):
                row_changes={'status':'parse_failed'}
            else:
                prior_raw=(db.execute('SELECT data FROM resources WHERE version_id=? AND name=?',
                                     (previous[0],'SmithData_C.bytes')).fetchone() if previous else None)
                old_rows={}
                previous_status='unavailable'
                if prior_raw:
                    try:
                        old_rows=smith_rows(prior_raw[0])
                        previous_status='parsed'
                    except (ValueError,TypeError,KeyError,OverflowError):
                        previous_status='parse_failed'
                saved=dict(db.execute('SELECT row_key,data FROM parsed_resource_rows WHERE version_id=? AND source=?',
                                      (current,'smith_v1')))
                if saved and saved!=new_rows:
                    raise ValueError('Smith rows changed for the same catalog identity')
                if not saved:
                    db.executemany('INSERT INTO parsed_resource_rows VALUES (?,?,?,?)',
                                   ((current,'smith_v1',key,value) for key,value in new_rows.items()))
                row_changes={'status':'parsed','count':len(new_rows),
                             'previous_available':previous_status=='parsed',
                             'previous_status':previous_status,
                             'added':sorted(new_rows.keys()-old_rows.keys()) if previous_status=='parsed' else [],
                             'changed':sorted(key for key in new_rows.keys() & old_rows.keys() if new_rows[key]!=old_rows[key]),
                             'removed':sorted(old_rows.keys()-new_rows.keys())}
        from wlre.services.world.npc_talk import parse_talk_data
        from wlre.services.expedition.data import parse_text_data
        from wlre.services.instance_catalog import parse_stages
        from wlre.services.world.eve_v115 import derive_eve_index
        def eve_rows(raw, source):
            doc = json.loads(derive_eve_index(raw, source))
            result = {}
            for scene, entries in doc['scenes'].items():
                for row in entries:
                    key = scene + ':' + str(row['index'])
                    if key in result:
                        raise ValueError('Duplicate Eve scene/index')
                    result[key] = row
            return result
        other_changes = {}
        for filename, source, parser in (
                ('TalkData_C.bytes', 'talk_v1', parse_talk_data),
                ('TextData_C.bytes', 'text_v1', parse_text_data),
                ('ScenesData_C.bytes', 'scenes_v1', parse_stages),
                ('Eve.bytes', 'eve_npc_v1', lambda raw: eve_rows(raw, 'EventData.NewNpc')),
                ('Eve.bytes', 'eve_interact_v1', lambda raw: eve_rows(raw, 'EventData.NewInteract'))):
            raw = tables.get(filename)
            if raw is None:
                continue
            try:
                parsed = parser(raw)
                rows = {str(k): json.dumps(v, ensure_ascii=True, sort_keys=True,
                                           separators=(',', ':')) for k, v in parsed.items()}
                prior_raw = (db.execute('SELECT data FROM resources WHERE version_id=? AND name=?',
                                        (previous[0], filename)).fetchone() if previous else None)
            except (ValueError, TypeError, KeyError, OverflowError):
                other_changes[source] = {'status': 'parse_failed'}
                continue
            old = {}
            previous_status = 'unavailable'
            if prior_raw:
                try:
                    old = {str(k): json.dumps(v, ensure_ascii=True, sort_keys=True,
                                             separators=(',', ':')) for k, v in parser(prior_raw[0]).items()}
                    previous_status = 'parsed'
                except (ValueError, TypeError, KeyError, OverflowError):
                    previous_status = 'parse_failed'
            saved = dict(db.execute('SELECT row_key,data FROM parsed_resource_rows WHERE version_id=? AND source=?',
                                    (current, source)))
            if saved and saved != rows:
                raise ValueError('Parsed rows changed for the same catalog identity')
            if not saved:
                db.executemany('INSERT INTO parsed_resource_rows VALUES (?, ?, ?, ?)',
                               ((current, source, k, v) for k, v in rows.items()))
            other_changes[source] = {'status': 'parsed', 'count': len(rows),
                                     'previous_available': previous_status == 'parsed',
                                     'previous_status': previous_status,
                                     'added': sorted(rows.keys() - old.keys()) if previous_status == 'parsed' else [],
                                     'changed': sorted(k for k in rows.keys() & old.keys() if rows[k] != old[k]),
                                     'removed': sorted(old.keys() - rows.keys())}
        return {'other_rows': other_changes, 'item_rows': item_changes, 'smith_rows': row_changes,
                'smith_legacy_comparison': legacy_recipe_changes, 'previous_available': previous is not None,
                'added': sorted(digests.keys() - prior.keys()) if previous else [],
                'changed': sorted(name for name in digests.keys() & prior.keys() if digests[name] != prior[name]),
                # A partial inventory cannot prove a table was removed.
                'missing_from_current': sorted(prior.keys() - digests.keys())}


def read_active_database_identity(path):
    """Return the active stored identity; this does not approve compatibility."""
    from pathlib import Path
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute('SELECT v.catalog_key, i.identity FROM sync_state s '
                             'JOIN versions v ON v.id=s.active_id '
                             'JOIN version_identities i ON i.version_id=v.id '
                             'WHERE s.singleton=1').fetchone()
        if not row or len(row[1]) > 4096 or hashlib.sha256(row[1].encode('ascii')).hexdigest() != row[0]:
            return None
        identity = json.loads(row[1])
        if (type(identity) is not dict or identity.get('schema_version') != 1
                or type(identity.get('packages')) is not list
                or {p.get('name') for p in identity['packages'] if type(p) is dict} != {'DataPackage', 'MainPackage'}
                or len(identity['packages']) != 2):
            return None
        return identity
    except (sqlite3.Error, OSError, ValueError, TypeError, UnicodeError):
        return None


def read_catalog_tables(path, catalog_key, sources):
    """Read and reparse requested tables from one database catalog identity.

    This is a read-only raw resource interface, not a gameplay authorization.
    Missing, damaged or unparseable inputs fail the entire requested snapshot.
    """
    from pathlib import Path
    from wlre.services.world.itemdata_v1 import parse_itemdata
    from wlre.services.world.npc_talk import parse_talk_data
    from wlre.services.expedition.data import parse_text_data
    from wlre.services.instance_catalog import parse_stages
    from wlre.services.world.eve_v115 import derive_eve_index
    from wlre.services.expedition.data import parse_catalog, attach_names, parse_npcs
    from wlre.services.world.smith_candidate import parse_smith_records
    parsers = {'items': ('ItemData_C.bytes', parse_itemdata),
               'talks': ('TalkData_C.bytes', parse_talk_data),
               'texts': ('TextData_C.bytes', parse_text_data),
               'scenes': ('ScenesData_C.bytes', parse_stages),
               'npc': ('Eve.bytes', lambda raw: json.loads(derive_eve_index(raw, 'EventData.NewNpc'))),
               'interactions': ('Eve.bytes', lambda raw: json.loads(derive_eve_index(raw, 'EventData.NewInteract')))}
    expedition_sources = {'AdventureData_C.bytes', 'AdventureLvData_C.bytes',
                          'NpcData_C.bytes', 'NpcCareerData_C.bytes', 'TextData_C.bytes'}
    if (type(catalog_key) is not str or len(catalog_key) != 64
            or any(c not in '0123456789abcdef' for c in catalog_key)
            or not isinstance(sources, (tuple, list)) or not sources
            or any(type(source) is not str for source in sources)
            or len(set(sources)) != len(sources) or any(source not in parsers and source not in ('expedition', 'recipes') for source in sources)):
        raise ValueError('Invalid catalog identity or source selection')
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Catalog database is unavailable')
    blobs = {}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            requested = {parsers[source][0] for source in sources if source not in ('expedition', 'recipes')}
            if 'expedition' in sources:
                requested.update(expedition_sources)
            if 'recipes' in sources:
                requested.update(('SmithData_C.bytes', 'ItemData_C.bytes'))
            for name in requested:
                row = db.execute('SELECT resources.sha256, resources.data FROM resources '
                                 'JOIN versions ON versions.id=resources.version_id '
                                 'WHERE versions.catalog_key=? AND resources.name=?',
                                 (catalog_key, name)).fetchone()
                if (row is None or type(row[1]) is not bytes or len(row[1]) > 16 * 1024 * 1024
                        or hashlib.sha256(row[1]).hexdigest() != row[0]):
                    raise ValueError('Catalog table missing or integrity check failed: ' + name)
                blobs[name] = row[1]
        result = {source: parsers[source][1](blobs[parsers[source][0]])
                  for source in sources if source not in ('expedition', 'recipes')}
        if 'expedition' in sources:
            quests = parse_catalog(blobs['AdventureData_C.bytes'], blobs['AdventureLvData_C.bytes'])
            quests = attach_names(quests, blobs['TextData_C.bytes'])
            result['expedition'] = {**quests, 'npcs': parse_npcs(
                blobs['NpcData_C.bytes'], blobs['NpcCareerData_C.bytes'])}
        if 'recipes' in sources:
            recipes = parse_smith_records(blobs['SmithData_C.bytes'])
            items = parse_itemdata(blobs['ItemData_C.bytes'])
            if any(row['item_id'] not in items or any(material['item_id'] not in items
                   for material in row['materials']) for row in recipes):
                raise ValueError('Recipe references missing item data')
            result['recipes'] = recipes
        return result
    except (sqlite3.Error, OSError) as exc:
        raise ValueError('Catalog database cannot be read') from exc


