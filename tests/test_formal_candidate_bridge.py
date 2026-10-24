"""Complete formal-runtime bridge tests, using offline synthetic data only."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from wlre.services.resource_compatibility import load_supported_resources
from wlre.services.world.auto_catalog import _ASSET_ROOT, _SOURCE_MAP
from wlre.services.world.catalog_adapters import FEATURES
from wlre.services.world.catalog_compatibility import (
    assess_candidate, read_compatibility_report, write_compatibility_report,
)
from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
from wlre.services.world.formal_candidate_bridge import (
    FormalBridgeError, _binding_sources, inspect_formal_bridge,
    promote_reviewed_archives,
)
from wlre.services.world.preview_1275 import (
    Preview1275, PreviewNPCIndex, PreviewInteractIndex,
)
from wlre.services.world import runtime_1275


class CandidateBridgeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'candidates'
        supported = load_supported_resources()
        self.identity = OfficialCatalogIdentity(
            '1.3.21', supported['official_game_exe_version'],
            tuple(PackageRevision(
                name, supported['packages'][name]['manifest'],
                ('a' if name == 'DataPackage' else 'b') * 64,
                ('12345678' if name == 'DataPackage' else '87654321'))
                for name in ('DataPackage', 'MainPackage')))
        self.npc = {
            '10000': [{'index': 3, 'npc_id': 9001, 'x': 20, 'y': 30,
                       'event_count': 0, 'event_ids': []}]}
        self.shops = {'10000': [{
            'index': 8, 'form_kind': 1, 'link_number': 0, 'items': []}]}
        self.raws = {
            'npc': json.dumps({'schema_version': 1, 'source': 'EventData.NewNpc',
                               'record_count': 1, 'scenes': self.npc}).encode(),
            'shops': json.dumps({'schema_version': 1,
                                 'source': 'EventData.NewInteract',
                                 'record_count': 1, 'scenes': self.shops}).encode(),
            'crafting': struct.pack('<i', 0),
            'scenes': struct.pack('<i', 0),
        }
        self.runtime = Preview1275(
            PreviewNPCIndex({'scenes': self.npc}),
            PreviewInteractIndex({'scenes': self.shops}),
            {}, {}, {}, {}, frozenset())
        sources = _binding_sources(self.identity)
        metadata = {
            'schema_version': 1, 'catalog_key': self.identity.key,
            'official_identity': self.identity.as_dict(),
            'status': 'review_required', 'approved': False,
            'assets_ready': False, 'can_send_packets': False,
            'features': {},
        }
        for src in sources:
            feature = src.binding.contract.feature
            binding = src.binding
            raw = self.raws[feature]
            metadata['features'][feature] = {
                'schema_id': binding.contract.schema_id,
                'package': binding.contract.package,
                'package_version': binding.contract.package_version,
                'source_name': binding.contract.source_name,
                'asset_path': binding.asset_path,
                'related_asset_paths': list(binding.related_asset_paths),
                'sha256': hashlib.sha256(raw).hexdigest(),
                'bytes': len(raw),
                'record_count': 1 if feature in ('npc', 'shops') else 0,
            }
        target = self.identity.private_catalog_dir(self.root)
        target.mkdir(parents=True)
        self.candidate = target / 'candidate.zip'
        with ZipFile(self.candidate, 'w') as z:
            z.writestr('candidate.json', json.dumps(metadata))
            for feature, raw in self.raws.items():
                z.writestr(feature + '.source', raw)
        report = assess_candidate(
            self.identity, sources, raw_by_feature=self.raws, metadata=metadata)
        write_compatibility_report(self.identity, report, candidate_root=self.root)

    def check(self, runtime=None):
        return inspect_formal_bridge(
            self.runtime if runtime is None else runtime,
            root=self.root, candidate_key=self.identity.key)

    def test_full_pinned_runtime_matches_four_candidates(self):
        result = self.check()
        self.assertEqual(result['status'], 'matches_formal_sources')
        self.assertEqual(result['checked_features'], list(FEATURES))
        self.assertFalse(result['can_send_packets'])
        self.assertFalse(result['assets_ready'])
        self.assertEqual(result['protocol_compatibility'], 'unverified')

    def test_different_official_npc_data_refuses_handoff(self):
        other = Preview1275(
            PreviewNPCIndex({'scenes': {'10000': []}}),
            self.runtime.interact_index,
            {}, {}, {}, {}, frozenset())
        with self.assertRaisesRegex(FormalBridgeError, 'NPC'):
            self.check(other)

    def test_substituted_candidate_and_stale_report_refused(self):
        self.candidate.write_bytes(b'replaced with untrusted bytes')
        with self.assertRaises(FormalBridgeError):
            self.check()

    def test_missing_compatibility_receipt_refused(self):
        folder = self.identity.private_catalog_dir(self.root)
        (folder / 'compatibility_report.json').unlink()
        with self.assertRaisesRegex(FormalBridgeError, 'report'):
            self.check()

    def test_without_complete_formal_archives_stays_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / 'reviewed'
            install = Path(tmp) / 'installed'
            result = promote_reviewed_archives(
                self.identity.key, candidate_root=self.root,
                reviewed_root=staging, install_root=install)
        self.assertEqual(result['status'], 'awaiting_complete_reviewed_archives')
        self.assertFalse(result['installed'])

    def test_partial_formal_archive_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / 'install'
            install.mkdir()
            (install / runtime_1275.DATA_FILE).write_bytes(b'old')
            with self.assertRaisesRegex(FormalBridgeError, 'Partial'):
                promote_reviewed_archives(
                    self.identity.key, candidate_root=self.root,
                    reviewed_root=Path(tmp) / 'reviewed', install_root=install)
            self.assertEqual((install / runtime_1275.DATA_FILE).read_bytes(), b'old')

    def test_formal_install_only_after_pinned_load_and_cross_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / 'reviewed'
            staging.mkdir()
            (staging / runtime_1275.DATA_FILE).write_bytes(b'data')
            (staging / runtime_1275.EVE_FILE).write_bytes(b'eve')
            install = Path(tmp) / 'install'
            def installer(data, eve, *, base, check_only):
                self.assertFalse(check_only)
                install.mkdir(exist_ok=True)
                (install / runtime_1275.DATA_FILE).write_bytes(b'data')
                (install / runtime_1275.EVE_FILE).write_bytes(b'eve')
                return {}
            with patch('wlre.services.world.preview_1275.load_preview',
                       return_value=self.runtime) as pinned, patch.object(
                           runtime_1275, 'install', side_effect=installer) as installed:
                output = promote_reviewed_archives(
                    self.identity.key, candidate_root=self.root,
                    reviewed_root=staging, install_root=install)
            self.assertEqual(output['status'], 'installed_and_verified')
            self.assertEqual(pinned.call_count, 2)
            installed.assert_called_once()

    def test_bad_pinned_formal_archive_cannot_trigger_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / 'reviewed'
            staging.mkdir()
            (staging / runtime_1275.DATA_FILE).write_bytes(b'bad')
            (staging / runtime_1275.EVE_FILE).write_bytes(b'eve')
            with patch('wlre.services.world.preview_1275.load_preview',
                       side_effect=ValueError('Bad pinned SHA')), patch.object(
                           runtime_1275, 'install') as installed:
                with self.assertRaisesRegex(ValueError, 'Bad pinned'):
                    promote_reviewed_archives(
                        self.identity.key, candidate_root=self.root,
                        reviewed_root=staging, install_root=Path(tmp) / 'install')
            installed.assert_not_called()

    def test_runtime_ready_blocks_mismatching_candidate_before_recipe_mutation(self):
        with patch.object(runtime_1275, 'active_runtime',
                          return_value=self.runtime), patch(
            'wlre.services.world.formal_candidate_bridge.inspect_launcher_candidate',
            side_effect=FormalBridgeError('Mismatch')), patch(
                'wlre.services.items.crafting.activate_1275_recipes') as mutate:
            ok, reason = runtime_1275.ready()
        self.assertFalse(ok)
        self.assertIn('Mismatch', reason)
        mutate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
