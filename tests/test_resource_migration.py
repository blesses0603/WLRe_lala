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

    def test_icon_and_emoji_archives_open_with_no_original_files(self):
        import zipfile
        from unittest.mock import patch
        from wlre.ui.crafting import item_icons
        from wlre.ui import chat_emoji
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'resources';root.mkdir();empty=base/'empty';empty.mkdir()
            (root/'item_icon_map.json').write_text('{"items":{}}')
            (root/'emoji_catalog.json').write_text('{"entries":{}}')
            for name in ('item_icons.zip','emoji_images.zip'):
                with zipfile.ZipFile(root/name,'w') as archive: archive.writestr('fixture',b'ok')
            db=base/'official_sync'/'derived_catalogs'/'resource_inventory.sqlite3'
            migrate_resources(root,db)
            with patch('wlre.storage.bundled_database.data_root',return_value=base), patch.object(item_icons,'BASE',empty), patch.object(chat_emoji,'RESOURCE_ROOT',empty):
                icons=item_icons.ItemIcons(None);emoji=chat_emoji.EmojiImages(None)
                try:
                    self.assertEqual(icons.archive.read('fixture'),b'ok')
                    self.assertEqual(emoji.archive.read('fixture'),b'ok')
                finally: icons.close();emoji.close()
