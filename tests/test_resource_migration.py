from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from wlre.storage.resource_migration import migrate_resources
from wlre.storage.bundled_database import load_bundled_bytes


class ResourceMigrationTests(unittest.TestCase):
    def test_clean_database_survives_original_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'resources'
            root.mkdir()
            expected = {'a.json': b'{"x":1}', 'b.zip': b'archive fixture'}
            for name, raw in expected.items(): (root / name).write_bytes(raw)
            db = Path(folder) / 'resources.sqlite3'
            self.assertEqual(migrate_resources(root, db), 2)
            for name in expected: (root / name).unlink()
            for name, raw in expected.items():
                self.assertEqual(load_bundled_bytes(name, root=root, database=db), raw)

    def test_corruption_refuses_migration_and_file_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'resources';root.mkdir()
            (root / 'a.json').write_bytes(b'{}')
            db = Path(folder) / 'resources.sqlite3'
            migrate_resources(root, db)
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute('UPDATE bundled_resources SET data=?', (b'bad',))
            with self.assertRaises(ValueError): migrate_resources(root, db)
            with self.assertRaises(ValueError): load_bundled_bytes('a.json', root=root, database=db)

    def test_source_changes_require_explicit_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'a.json';db=root/'resources.sqlite3'
            source.write_bytes(b'old');migrate_resources(root, db)
            source.write_bytes(b'new')
            self.assertEqual(load_bundled_bytes('a.json',root=root,database=db),b'old')
            self.assertEqual(load_bundled_bytes('a.json',root=root,database=db,refresh=True),b'new')

    def test_cold_icons_and_emoji_never_read_bundled_files(self):
        from unittest.mock import patch
        from wlre.ui.crafting.item_icons import ItemIcons, ICON_MAP
        from wlre.ui.chat_emoji import EmojiImages
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=None),patch(
                'wlre.storage.bundled_database.load_bundled_bytes',side_effect=AssertionError('retired resources')):
            icons=ItemIcons(None);emoji=EmojiImages(None)
            self.assertEqual(dict(ICON_MAP),{})
            self.assertIsNone(icons._pixels(1,16).getbbox())
            self.assertEqual(emoji.catalog,{})
            icons.close();emoji.close()
