"""1275 expedition integration regression; no official binary or network needed."""
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from wlre.network.wire import ProtocolError
from wlre.services.expedition import data
from wlre.services.expedition.manager import Expedition
from wlre.core.state import State


class VerifiedExpedition1275Tests(unittest.TestCase):
    TABLES = ('AdventureData_C', 'AdventureLvData_C',
              'NpcData_C', 'NpcCareerData_C')

    def fixture(self, folder):
        root = Path(folder)
        archive = root / '1275_DataCatalog.zip'
        rows = {name: name.encode('ascii') + b'-fixture' for name in self.TABLES}
        manifest = {'files': {
            'tables/datapackage_data_a.bundle/' + table + '.bytes': {
                'kind': 'raw_table', 'table': table,
                'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()
            } for table, raw in rows.items()
        }}
        with ZipFile(archive, 'w') as zip_file:
            for table, raw in rows.items():
                zip_file.writestr('tables/datapackage_data_a.bundle/' + table + '.bytes', raw)
        return root, archive, rows, manifest

    def test_pinned_archive_routes_1275_text_npcs_and_tasks_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, archive, rows, manifest = self.fixture(tmp)
            parsed = {'tasks': {
                str(i): {'id': i, 'name_id': 100, 'area_name': 200}
                for i in range(1, 261)},
                'levels': {str(i): {'teams': 2} for i in range(1, 11)},
                'source_sha256': {'AdventureData_C': 'a' * 64},
            }
            npcs = {str(i): {'original': i} for i in range(1, 7562)}
            with patch('wlre.services.world.runtime_1275.baseline_revision',
                       return_value='1275'), \
                 patch('wlre.services.world.runtime_1275.active_runtime',
                       return_value=SimpleNamespace(
                           revision=1275, texts={100: '新版遠征名稱', 200: '新版地區'})), \
                 patch('wlre.services.world.runtime_1275.resource_dir',
                       return_value=root), \
                 patch('wlre.services.world.game_data_1275.verify_archive') as verify, \
                 patch('wlre.services.world.game_data_1275.read_manifest',
                       return_value=manifest), \
                 patch('wlre.services.expedition.data.parse_catalog',
                       return_value=parsed), \
                 patch('wlre.services.expedition.data.parse_npcs',
                       return_value=npcs), \
                 patch.object(data, 'ADVENTURE_1275_SHA256',
                              hashlib.sha256(rows['AdventureData_C']).hexdigest()), \
                 patch.object(data, 'ADVENTURE_LEVEL_1275_SHA256',
                              hashlib.sha256(rows['AdventureLvData_C']).hexdigest()):
                result = data.load_verified_1275_catalog()
                verify.assert_called_once_with(archive)
                self.assertEqual(len(result['tasks']), 260)
                self.assertEqual(len(result['npcs']), 7561)
                self.assertEqual(len(result['levels']), 10)
                self.assertEqual(result['tasks']['1']['name'], '新版遠征名稱')
                self.assertEqual(result['tasks']['1']['area_label'], '新版地區')
                self.assertEqual(result['revision'], 1275)
                self.assertEqual(result['source_kind'], 'verified_1275_full_archive')
                self.assertNotIn('can_send_packets', result)

    def test_refuses_wrong_base_version_without_using_legacy_catalog(self):
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1262'), \
             patch('wlre.services.world.runtime_1275.active_runtime') as active:
            with self.assertRaises(ValueError):
                data.load_verified_1275_catalog()
            active.assert_not_called()

    def test_active_catalog_refuses_silent_legacy_fallback(self):
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), \
             patch.object(data, 'load_verified_1275_catalog',
                          side_effect=ValueError('bad formal asset')), \
             patch.object(data, 'load_catalog') as legacy:
            with self.assertRaisesRegex(ValueError, 'bad formal asset'):
                data.load_active_catalog()
            legacy.assert_not_called()

    def test_manager_start_does_not_dispatch_without_verified_1275(self):
        state = State()
        state.expedition.update(ready=True, outpost_ready=True, level=1)
        service = Expedition()
        with patch('wlre.services.expedition.manager.load_active_catalog',
                   side_effect=ValueError('1275 missing')):
            with self.assertRaisesRegex(ProtocolError, '禁止自動派遣'):
                service.start(state, {})
        self.assertFalse(state.expedition['enabled'])
        self.assertIsNone(service.pending)


if __name__ == '__main__':
    unittest.main()
