"""No-network resource gap detection, same pinned 1275 contracts as runtime."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from wlre.services.world import resource_gap_diagnostics as diag
from wlre.services.world import runtime_1275


class ResourceGapTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.formal = self.root / runtime_1275.FOLDER
        self.formal.mkdir()

    def test_missing_legacy_zips_do_not_hide_official_bundle_error(self):
        from wlre.services.world.runtime_1275 import Runtime1275Unavailable
        missing = (
            self.formal / '1275_DataCatalog.zip',
            self.formal / '1275_EveNpcIndex.zip')
        with patch.object(runtime_1275, 'active_runtime',
                          side_effect=Runtime1275Unavailable(
                              '1275 官方 Bundle 尚未完成完整核對：仍缺少官方 Bundle：Eve')), \
             patch.object(runtime_1275, '_paths', return_value=missing), \
             patch.object(diag, 'diagnose_resources') as zip_diagnose, \
             patch('wlre.services.world.launcher_catalog.read_launcher_status',
                   return_value=None):
            ready, detail = runtime_1275.ready()
        self.assertFalse(ready)
        self.assertIn('缺少官方 Bundle：Eve', detail)
        self.assertNotIn('1275_DataCatalog', detail)
        zip_diagnose.assert_not_called()

    def test_installed_corrupt_zip_keeps_exact_legacy_diagnostic(self):
        from wlre.services.world.runtime_1275 import Runtime1275Unavailable
        broken_zip = self.formal / '1275_DataCatalog.zip'
        broken_zip.write_bytes(b'corrupt zip')
        sources = (
            broken_zip, self.formal / '1275_EveNpcIndex.zip')
        with patch.object(runtime_1275, 'active_runtime',
                          side_effect=Runtime1275Unavailable(
                              '1275 正式資源驗證失敗')), \
             patch.object(runtime_1275, '_paths', return_value=sources), \
             patch.object(diag, 'diagnose_resources',
                          return_value=diag.diagnose_resources(base=self.root)):
            ready, detail = runtime_1275.ready()
        self.assertFalse(ready)
        self.assertIn('損壞或內容不符', detail)
        self.assertIn('1275_DataCatalog', detail)

    def test_bundle_loader_retains_sanitized_reason(self):
        from wlre.services.world.bundle_runtime_1275 import BundleRuntimeUnavailable
        missing = (
            self.formal / '1275_DataCatalog.zip',
            self.formal / '1275_EveNpcIndex.zip')
        runtime_1275._default_runtime.cache_clear()
        self.addCleanup(runtime_1275._default_runtime.cache_clear)
        with patch.object(runtime_1275, '_paths', return_value=missing), \
             patch('wlre.services.world.bundle_runtime_1275.load_verified_bundle_runtime',
                   side_effect=BundleRuntimeUnavailable(
                       '仍缺少官方 Bundle：SmithData_C')):
            with self.assertRaisesRegex(
                    runtime_1275.Runtime1275Unavailable, 'SmithData_C'):
                runtime_1275._default_runtime()

    def test_missing_both_archives_reports_exact_required_groups(self):
        r = diag.diagnose_resources(base=self.root)
        self.assertFalse(r['formal_ready'])
        self.assertEqual(r['formal_sources'][diag.ARCHIVES[0]]['state'], 'missing')
        self.assertEqual(r['formal_sources'][diag.ARCHIVES[1]]['state'], 'missing')
        self.assertIn('TalkData_C', r['missing_groups'])
        self.assertIn('TextData_C', r['missing_groups'])
        self.assertIn('ItemData_C', r['missing_groups'])
        self.assertIn('160 張原始資料表', r['missing_groups'])
        self.assertIn('NPC 事件索引', r['missing_groups'])
        self.assertIn('NPC 互動選單索引', r['missing_groups'])
        self.assertFalse(r['assets_ready'])
        self.assertFalse(r['can_send_packets'])
        self.assertIn('1275_DataCatalog', diag.summarize(r))

    def test_one_archive_present_but_invalid_is_not_misreported_as_missing(self):
        (self.formal / diag.ARCHIVES[0]).write_bytes(b'not a ZIP')
        r = diag.diagnose_resources(base=self.root)
        self.assertEqual(r['formal_sources'][diag.ARCHIVES[0]]['state'], 'invalid')
        self.assertEqual(r['formal_sources'][diag.ARCHIVES[1]]['state'], 'missing')
        self.assertIn('損壞', diag.summarize(r))
        self.assertIn('缺少', diag.summarize(r))

    def test_pinned_data_manifest_lists_exact_missing_inner_members(self):
        archive = self.formal / diag.ARCHIVES[0]
        with ZipFile(archive, 'w') as z:
            z.writestr('manifest.json', b'not a real pinned manifest')
            z.writestr('使用說明.txt', 'readme')
        expected = {'tables/datapackage_data_a.bundle/SmithData_C.bytes':
                    {'bytes': 128, 'sha256': '0' * 64},
                    'indexes/npc_item_data_1275.json.gz':
                    {'bytes': 256, 'sha256': '1' * 64}}
        with patch.object(diag, 'read_manifest', return_value={'files': expected}), \
             patch.object(diag, 'verify_archive') as verify:
            r = diag.diagnose_resources(base=self.root)
        member = r['formal_sources'][diag.ARCHIVES[0]]
        self.assertEqual(member['state'], 'invalid')
        self.assertEqual(set(member['missing']), set(expected))
        verify.assert_not_called()

    def test_corrupted_pinned_table_reports_exact_member(self):
        archive = self.formal / diag.ARCHIVES[0]
        name = 'tables/datapackage_data_a.bundle/SmithData_C.bytes'
        raw = b'official table corrupted in this synthetic test'
        with ZipFile(archive, 'w') as z:
            z.writestr('manifest.json', b'fake pinned JSON')
            z.writestr('使用說明.txt', 'readme')
            z.writestr(name, raw)
        manifest = {'files': {name: {
            'bytes': len(raw), 'sha256': '0' * 64}}}
        with patch.object(diag, 'read_manifest', return_value=manifest), \
             patch.object(diag, 'verify_archive',
                          side_effect=ValueError('SHA mismatch')):
            report = diag.diagnose_resources(base=self.root)
        self.assertIn(name, report['formal_sources'][diag.ARCHIVES[0]]['invalid'])

    def test_corrupted_eve_index_identifies_affected_file(self):
        archive = self.formal / diag.ARCHIVES[1]
        with ZipFile(archive, 'w') as z:
            z.writestr('README.txt', 'readme')
            for name in diag.EVE_FILES:
                z.writestr(name, b'incorrect source size')
        report = diag.diagnose_resources(base=self.root)
        self.assertEqual(set(report['formal_sources'][diag.ARCHIVES[1]]['invalid']),
                         set(diag.EVE_FILES))

    def test_eve_missing_inner_index_is_explicit(self):
        archive = self.formal / diag.ARCHIVES[1]
        with ZipFile(archive, 'w') as z:
            z.writestr('README.txt', 'readme')
            z.writestr('npc_event_index_1275.json.gz', b'dummy')
        r = diag.diagnose_resources(base=self.root)
        self.assertEqual(
            r['formal_sources'][diag.ARCHIVES[1]]['missing'],
            ['npc_interact_1275.json.gz'])

    def test_verified_sources_still_do_not_grant_packet_permission(self):
        d = self.formal / diag.ARCHIVES[0]
        e = self.formal / diag.ARCHIVES[1]
        with ZipFile(d, 'w') as z:
            z.writestr('manifest.json', b'dummy pinned manifest')
            z.writestr('使用說明.txt', 'test')
        with ZipFile(e, 'w') as z:
            z.writestr('README.txt', 'readme')
            for name in diag.EVE_FILES:
                z.writestr(name, b'fixture')
        with patch.object(diag, 'read_manifest', return_value={'files': {}}), \
             patch.object(diag, 'verify_archive') as checked_data, \
             patch.object(diag, 'read_verified_zip') as checked_eve:
            r = diag.diagnose_resources(base=self.root)
        checked_data.assert_called_once_with(d)
        checked_eve.assert_called_once_with(e)
        self.assertTrue(r['formal_ready'])
        self.assertEqual(r['missing_groups'], [])
        self.assertFalse(r['assets_ready'])
        self.assertFalse(r['can_send_packets'])

    def test_report_is_atomic_and_rejects_old_or_modified_entries(self):
        report = diag.diagnose_resources(
            base=self.root, checked_at_utc='2026-10-24T19:00:00+00:00')
        diag.save_report(report, base=self.root)
        self.assertEqual(diag.read_report(
            base=self.root, expected_checked_at_utc=report['checked_at_utc']), report)
        self.assertIsNone(diag.read_report(
            base=self.root, expected_checked_at_utc='2026-10-24T19:01:00+00:00'))
        report['assets_ready'] = True
        diag.report_path(self.root).write_text(json.dumps(report), encoding='utf-8')
        self.assertIsNone(diag.read_report(base=self.root))
        diag.report_path(self.root).write_bytes(b'X' * (diag.MAX_REPORT_BYTES + 1))
        self.assertIsNone(diag.read_report(base=self.root))

    def test_cli_prints_required_groups_without_network(self):
        from tools import diagnose_lala_resources
        with patch.object(diagnose_lala_resources, 'diagnose_resources',
                          return_value=diag.diagnose_resources(base=self.root)), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(diagnose_lala_resources.main([]), 0)
        self.assertIn('TalkData_C', output.getvalue())
        self.assertIn('NPC 事件索引', output.getvalue())


if __name__ == '__main__':
    unittest.main()
