"""Safety tests for 1275 opt-in indexes, without shipping copyrighted tables."""
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from wlre.services.world.npc_1275_assets import (
    INDEXES, install, load_read_only, read_verified, verify_index,
)


class NewIndexTests(unittest.TestCase):
    def test_rejects_corrupt_catalog(self):
        with self.assertRaises(ValueError):
            verify_index('npc_talk_1275.json.gz', b'not a gzip')
        with self.assertRaises(ValueError):
            verify_index('npc_item_data_1262.json.gz', b'')

    def test_fail_closed_before_writing_anything(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / 'assets.zip'
            with ZipFile(archive, 'w') as z:
                for name in INDEXES:
                    z.writestr('wlre/resources/' + name, b'corrupted')
            with self.assertRaises(ValueError):
                install(archive, root, check_only=False)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['assets.zip'])

    def test_verified_install_and_existing_file_guard(self):
        data = {'version': 1275, 'source': 'ItemData_C',
                'source_sha256': 'source-digest', 'record_count': 1,
                'records': {'32297': {'name': '果粒蘋果汁', 'price': 750,
                                       'sell_price': 8, 'restrict': 15,
                                       'open_used': 0, 'need_level': 0}}}
        raw = gzip.compress(json.dumps(data, ensure_ascii=False).encode('utf-8'), mtime=0)
        pinned = ('ItemData_C', 'source-digest', hashlib.sha256(raw).hexdigest(),
                  len(raw), 1)
        name = 'npc_item_data_1275.json.gz'
        with patch.dict(INDEXES, {name: pinned}, clear=True), tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / 'valid.zip'
            with ZipFile(archive, 'w') as z:
                z.writestr('wlre/resources/' + name, raw)
            self.assertEqual(install(archive, root, check_only=True), {name: len(raw)})
            self.assertFalse((root/name).exists())
            self.assertEqual(install(archive, root, check_only=False), {name: len(raw)})
            self.assertEqual(load_read_only(name, root)['32297']['price'], 750)
            with self.assertRaises(FileExistsError):
                install(archive, root, check_only=False)

    def test_no_overwrite_or_unexpected_zip_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            root.joinpath('npc_item_data_1262.json.gz').write_bytes(b'legacy')
            archive = root / 'assets.zip'
            with ZipFile(archive, 'w') as z:
                z.writestr('../../evil', b'bad')
            with self.assertRaises(KeyError):
                read_verified(archive)
            self.assertEqual(root.joinpath('npc_item_data_1262.json.gz').read_bytes(), b'legacy')
            self.assertFalse(root.joinpath('evil').exists())


if __name__ == '__main__':
    unittest.main()
