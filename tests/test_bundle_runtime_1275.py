"""Offline activation tests: audited .bytes/.hash + Bundles, never manual ZIPs."""
from contextlib import ExitStack
import hashlib
import json
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from wlre.services.official_manifest_sync import ManifestSpec
from wlre.services.world.bundle_runtime_1275 import (
    BundleRuntimeUnavailable, load_verified_bundle_runtime,
    sync_pinned_runtime_bundles)


class VerifiedBundleRuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'official_sync'
        self.root.mkdir()
        self.pinned = {}
        self.verified = {}
        for package, version in (
                ('DataPackage', '1275_2026_10_21_18_27_33_84'),
                ('MainPackage', '1275_2026_10_21_18_29_38_49')):
            raw = b'audited manifest fixture for ' + package.encode()
            path = self.root / (package + '.bytes')
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            self.pinned[package] = digest
            self.verified[package] = SimpleNamespace(
                spec=ManifestSpec('1.3.21', package, version),
                cache_path=path, hash_text='ab12cd34')
        self.supported = {'packages': {
            package: {'revision': '1275',
                      'manifest': self.verified[package].spec.package_version}
            for package in ('DataPackage', 'MainPackage')}}
        self.key = 'a' * 64
        self.identity = SimpleNamespace(
            key=self.key, data_ver='1.3.21', packages=tuple(
                SimpleNamespace(name=name,
                                full_version=self.verified[name].spec.package_version,
                                manifest_sha256=self.pinned[name],
                                manifest_crc32_le='ab12cd34')
                for name in ('DataPackage', 'MainPackage')))
        self.receipt = {
            'status': 'review_required', 'catalog_key': self.key,
            'data_compatibility': 'compatible', 'can_send_packets': False}
        self.raw = {
            name: name.encode() for name in (
                'Eve', 'ItemData_C', 'TalkData_C', 'TextData_C',
                'SmithData_C', 'ScenesData_C',
                'AdventureData_C', 'AdventureLvData_C',
                'NpcData_C', 'NpcCareerData_C')}
        self.raw['StageMapData_C'] = struct.pack('<i', 0)
        self.raw['EveDoorLinks'] = '事件ID=10000\n'.encode('utf-16-le')
        self.items = {i: {'name': f'物品{i}', 'open_used': 0} for i in range(1, 1033)}
        self.recipes = {
            i: {'item_id': i, 'tool_id': 39053, 'output': 1,
                'materials': [], 'seconds': 1, 'order': i,
                'design_id': 0, 'time_id': 0, 'limit_kind': 0}
            for i in range(1, 1033)}
        self.scenes = {str(10000+i): [] for i in range(1262)}
        self.expedition_tasks = {
            str(i): {'id': i, 'name_id': 3, 'area_name': 3}
            for i in range(1, 261)}
        self.expedition_levels = {str(i): {'teams': 1} for i in range(1, 11)}
        self.expedition_npcs = {
            str(i): {'kind': 1} for i in range(1, 7562)}
        self.extract = Mock(side_effect=lambda binding, paths, loader=None:
                            self.raw[binding.contract.source_name])
        self.plan = SimpleNamespace(entries=[
            SimpleNamespace(
                action='cached',
                spec=SimpleNamespace(cache_path=lambda root: self.root / 'verified.bundle'))
        ])

    def patches(self, stack):
        stack.enter_context(patch(
            'wlre.services.world.bundle_runtime_1275._PINNED_MANIFEST_SHA256',
            self.pinned))
        stack.enter_context(patch(
            'wlre.services.resource_compatibility.load_supported_resources',
            return_value=self.supported))
        stack.enter_context(patch(
            'wlre.services.world.launcher_catalog.read_launcher_status',
            return_value=self.receipt))
        stack.enter_context(patch(
            'wlre.services.world.auto_catalog._trusted_cached_candidate',
            return_value={'catalog_key': self.key}))
        stack.enter_context(patch(
            'wlre.services.world.formal_candidate_bridge._identity_from_metadata',
            return_value=self.identity))
        stack.enter_context(patch(
            'wlre.services.official_manifest_sync.read_verified_cached_manifest',
            side_effect=lambda spec, cache_root=None: self.verified[spec.package]))
        stack.enter_context(patch(
            'wlre.services.official_incremental_sync.build_update_plan',
            return_value=self.plan))
        stack.enter_context(patch(
            'wlre.services.official_bundle_download._verified_file',
            return_value=True))
        stack.enter_context(patch(
            'wlre.services.world.unity_textasset.extract_textasset',
            self.extract))
        stack.enter_context(patch(
            'wlre.services.world.doors_1275.SOURCE_SHA256',
            hashlib.sha256(self.raw['Eve']).hexdigest()))
        stack.enter_context(patch(
            'wlre.services.world.eve_v115.derive_eve_index',
            side_effect=lambda raw, kind: json.dumps({
                'record_count': (10975 if kind == 'EventData.NewNpc' else 1634),
                'scenes': self.scenes if kind == 'EventData.NewNpc'
                          else {'10000': [{'index': 1, 'form_kind': 1}]},
            }).encode()))
        stack.enter_context(patch(
            'wlre.services.world.itemdata_v1.parse_itemdata',
            return_value=self.items))
        stack.enter_context(patch(
            'wlre.services.world.npc_talk.parse_talk_data',
            return_value={2: {'text': '官方 NPC 對話'}}))
        stack.enter_context(patch(
            'wlre.services.expedition.data.parse_text_data',
            return_value={3: '正式文字'}))
        stack.enter_context(patch(
            'wlre.services.world.preview_1275.parse_smith_1275',
            return_value=self.recipes))
        stack.enter_context(patch(
            'wlre.services.expedition.data.ADVENTURE_1275_SHA256',
            hashlib.sha256(self.raw['AdventureData_C']).hexdigest()))
        stack.enter_context(patch(
            'wlre.services.expedition.data.ADVENTURE_LEVEL_1275_SHA256',
            hashlib.sha256(self.raw['AdventureLvData_C']).hexdigest()))
        stack.enter_context(patch(
            'wlre.services.expedition.data.parse_catalog',
            return_value={
                'tasks': self.expedition_tasks,
                'levels': self.expedition_levels,
                'source_sha256': {
                    'AdventureData_C': hashlib.sha256(
                        self.raw['AdventureData_C']).hexdigest(),
                    'AdventureLvData_C': hashlib.sha256(
                        self.raw['AdventureLvData_C']).hexdigest()}}))
        stack.enter_context(patch(
            'wlre.services.expedition.data.parse_npcs',
            return_value=self.expedition_npcs))
        stack.enter_context(patch(
            'wlre.services.instance_catalog.parse_stages',
            return_value={10000: {}}))
        stack.enter_context(patch(
            'wlre.services.world.doors_1275.parse_doors_1275',
            return_value={}))

    def _official_snapshot(self):
        return {
            'schema_version': 1,
            'origin': 'official_pc_version_endpoint',
            'data_ver': '1.3.21',
            'exe_version': '1.3.0',
            'packages': {
                package: self.verified[package].spec.package_version
                for package in ('DataPackage', 'MainPackage')},
            'checked_at_utc': '2026-10-25T00:00:00+00:00',
            'assets_ready': False,
        }

    def test_pinned_runtime_sync_does_not_require_four_feature_candidate(self):
        snapshot = self._official_snapshot()
        supported = {
            'official_game_exe_version': '1.3.0', **self.supported}
        entries = [SimpleNamespace(
            action='download',
            spec=SimpleNamespace(file_size=1234,
                                 cache_path=lambda root: self.root / 'synthetic.bundle'))]
        sync = Mock()
        with patch('wlre.services.world.bundle_runtime_1275._PINNED_MANIFEST_SHA256',
                   self.pinned), patch(
             'wlre.services.resource_compatibility.load_supported_resources',
             return_value=supported), patch(
             'wlre.services.official_incremental_sync.build_update_plan',
             return_value=SimpleNamespace(entries=entries)) as plan, patch(
             'wlre.services.official_bundle_download._verified_file',
             return_value=True):
            result = sync_pinned_runtime_bundles(
                sync_root=self.root, observe=lambda: snapshot,
                retrieve=lambda spec, cache_root: self.verified[spec.package],
                execute=sync)
        self.assertEqual(result['verified_bundles'], 1)
        self.assertEqual(result['downloaded_bundles'], 1)
        self.assertFalse(result['assets_ready'])
        self.assertFalse(result['can_send_packets'])
        self.assertEqual(plan.call_count, 2)
        self.assertEqual(len(plan.call_args_list[0].kwargs['asset_paths']), 10)
        self.assertEqual(len(plan.call_args_list[1].kwargs['asset_paths']), 2)
        self.assertEqual(sync.call_count, 2)
        self.assertTrue(result['portal_metadata_ready'])

    def test_optional_portal_bundle_failure_keeps_core_runtime_ready(self):
        snapshot = self._official_snapshot()
        supported = {'official_game_exe_version': '1.3.0', **self.supported}
        rows = [SimpleNamespace(
            action='download',
            spec=SimpleNamespace(file_size=512,
                                 cache_path=lambda root: self.root / 'verified.bundle'))]
        execute = Mock(side_effect=[None, ValueError('optional portal asset failed')])
        with patch('wlre.services.world.bundle_runtime_1275._PINNED_MANIFEST_SHA256',
                   self.pinned), patch(
             'wlre.services.resource_compatibility.load_supported_resources',
             return_value=supported), patch(
             'wlre.services.official_incremental_sync.build_update_plan',
             return_value=SimpleNamespace(entries=rows)), patch(
             'wlre.services.official_bundle_download._verified_file',
             return_value=True):
            result = sync_pinned_runtime_bundles(
                sync_root=self.root, observe=lambda: snapshot,
                retrieve=lambda spec, cache_root: self.verified[spec.package],
                execute=execute)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(result['downloaded_bundles'], 1)
        self.assertFalse(result['portal_metadata_ready'])
        self.assertFalse(result['can_send_packets'])

    def test_pinned_runtime_sync_rejects_version_switch_before_download(self):
        snapshot = self._official_snapshot()
        switched = {**snapshot, 'packages': {
            **snapshot['packages'],
            'DataPackage': '1276_2026_10_25_00_00_00_00'}}
        observed = iter((snapshot, switched))
        supported = {
            'official_game_exe_version': '1.3.0', **self.supported}
        sync = Mock()
        with patch('wlre.services.world.bundle_runtime_1275._PINNED_MANIFEST_SHA256',
                   self.pinned), patch(
             'wlre.services.resource_compatibility.load_supported_resources',
             return_value=supported), patch(
             'wlre.services.official_incremental_sync.build_update_plan',
             return_value=SimpleNamespace(entries=[])):
            with self.assertRaisesRegex(BundleRuntimeUnavailable, '版本變動'):
                sync_pinned_runtime_bundles(
                    sync_root=self.root, observe=lambda: next(observed),
                    retrieve=lambda spec, cache_root: self.verified[spec.package],
                    execute=sync)
        sync.assert_not_called()

    def test_pinned_runtime_sync_rejects_manifest_sha_change(self):
        snapshot = self._official_snapshot()
        supported = {
            'official_game_exe_version': '1.3.0', **self.supported}
        pins = {**self.pinned, 'MainPackage': '0' * 64}
        sync = Mock()
        with patch('wlre.services.world.bundle_runtime_1275._PINNED_MANIFEST_SHA256',
                   pins), patch(
             'wlre.services.resource_compatibility.load_supported_resources',
             return_value=supported):
            with self.assertRaisesRegex(BundleRuntimeUnavailable, 'SHA-256'):
                sync_pinned_runtime_bundles(
                    sync_root=self.root, observe=lambda: snapshot,
                    retrieve=lambda spec, cache_root: self.verified[spec.package],
                    execute=sync)
        sync.assert_not_called()

    def test_bundle_sources_become_real_runtime_data_not_ui_candidate(self):
        with ExitStack() as stack:
            self.patches(stack)
            runtime = load_verified_bundle_runtime(sync_root=self.root)
        self.assertEqual(runtime.revision, 1275)
        self.assertEqual(len(runtime.recipes), 1032)
        self.assertEqual(runtime.recipe(20)['tool_id'], 39053)
        self.assertEqual(runtime.items[20]['name'], '物品20')
        self.assertEqual(runtime.talks[2], '官方 NPC 對話')
        self.assertEqual(runtime.texts[3], '正式文字')
        self.assertTrue(runtime.portal_status(10000)['exists'])
        self.assertFalse(runtime.can_send_packets)
        self.assertEqual(self.extract.call_count, 12)
        self.assertEqual(len(runtime.expedition['tasks']), 260)
        self.assertEqual(runtime.expedition['tasks']['1']['name'], '正式文字')
        self.assertEqual(runtime.expedition['source_kind'],
                         'verified_1275_official_bundle')

    def test_portal_names_survive_missing_optional_eve_door_links(self):
        # The official minimap label is StageMapData.NameID, not a transfer
        # destination. Failure to load EveDoorLinks must not erase the name.
        self.raw['StageMapData_C'] = (
            struct.pack('<i', 1) +
            struct.pack('<HBHIHHIB', 10000, 2, 0, 1, 500, 600, 3, 0))
        def extract(binding, paths, loader=None):
            name = binding.contract.source_name
            if name == 'EveDoorLinks':
                raise ValueError('optional link not available')
            return self.raw[name]
        self.extract.side_effect = extract
        with ExitStack() as stack:
            self.patches(stack)
            runtime = load_verified_bundle_runtime(sync_root=self.root)
        self.assertEqual(runtime.portal_names, {(10000, 1): '正式文字'})
        self.assertEqual(runtime.portal_destinations, {})
        self.assertEqual(runtime.portal_metadata_status,
                         'destination_links_missing_or_invalid')
        self.assertEqual(len(runtime.recipes), 1032)

    def test_optional_stage_map_not_cached_reports_precise_reason(self):
        from wlre.services.official_incremental_sync import build_update_plan
        plan = build_update_plan
        def fake_plan(manifest, *, asset_paths, cache_root):
            if 'StageMapData_C.bytes' in asset_paths[0]:
                return SimpleNamespace(entries=[SimpleNamespace(action='download')])
            return self.plan
        with ExitStack() as stack:
            self.patches(stack)
            stack.enter_context(patch(
                'wlre.services.official_incremental_sync.build_update_plan',
                side_effect=fake_plan))
            runtime = load_verified_bundle_runtime(sync_root=self.root)
        self.assertEqual(runtime.portal_metadata_status, 'bundle_not_cached')
        self.assertEqual(runtime.portal_names, {})
        self.assertEqual(runtime.portal_display_destinations, {})
        self.assertEqual(len(runtime.recipes), 1032)

    def test_optional_stage_map_extraction_error_is_not_silenced(self):
        def extract(binding, paths, loader=None):
            if binding.contract.source_name == 'StageMapData_C':
                raise ValueError('malformed UnityFS text asset')
            return self.raw[binding.contract.source_name]
        self.extract.side_effect = extract
        with ExitStack() as stack:
            self.patches(stack)
            runtime = load_verified_bundle_runtime(sync_root=self.root)
        self.assertEqual(runtime.portal_metadata_status, 'textasset_extract_failed')
        self.assertEqual(runtime.portal_names, {})
        self.assertEqual(len(runtime.recipes), 1032)

    def test_verified_bundle_data_enters_real_crafting_plan(self):
        # This is the actual crafting service, not a read-only UI preview.
        # Packet construction is tested offline; no game session is contacted.
        from wlre.services.items.crafting import RECIPES, recipe_plan
        from wlre.services.world import runtime_1275
        saved = dict(RECIPES)
        self.addCleanup(lambda: (RECIPES.clear(), RECIPES.update(saved)))
        with ExitStack() as stack:
            self.patches(stack)
            source = load_verified_bundle_runtime(sync_root=self.root)
            stack.enter_context(patch.object(
                runtime_1275, 'active_runtime', return_value=source))
            stack.enter_context(patch(
                'wlre.services.world.formal_candidate_bridge.inspect_launcher_candidate',
                return_value={'status': 'not_requested'}))
            enabled, details = runtime_1275.ready()
        self.assertTrue(enabled)
        self.assertIn('協定仍須獨立驗收', details)
        self.assertEqual(len(RECIPES), 1032)
        self.assertEqual(RECIPES['20']['open_used'], 0)
        player = {'role_id': 42}
        state = SimpleNamespace(
            player=player,
            furniture={'ready': True, 'owner': 42,
                       'items': {'1': {'item_id': 39053, 'index': 1, 'status': 0}}},
            crafting={'ready': True, 'queue': {}},
            inventory={'ready': True, 'reliable': True, 'items': {}})
        recipe, allocations, packet = recipe_plan(state, 20, 1)
        self.assertEqual(recipe['item_id'], 20)
        self.assertEqual(allocations, [])
        self.assertEqual((packet.main, packet.sub), (64, 1))

    def test_official_expedition_service_uses_active_bundle_catalog(self):
        from wlre.services.expedition.data import load_verified_1275_catalog
        with ExitStack() as stack:
            self.patches(stack)
            runtime = load_verified_bundle_runtime(sync_root=self.root)
            stack.enter_context(patch(
                'wlre.services.world.runtime_1275.baseline_revision',
                return_value='1275'))
            stack.enter_context(patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime))
            catalog = load_verified_1275_catalog()
        self.assertEqual(len(catalog['tasks']), 260)
        self.assertEqual(len(catalog['levels']), 10)
        self.assertEqual(len(catalog['npcs']), 7561)
        self.assertEqual(catalog['tasks']['1']['name'], '正式文字')
        catalog['tasks']['1']['name'] = '被 UI 修改'
        self.assertEqual(runtime.expedition['tasks']['1']['name'], '正式文字')

    def test_missing_or_corrupt_official_bundle_never_activates(self):
        for action in ('download', 'reuse_previous', 'cached'):
            with self.subTest(action=action), ExitStack() as stack:
                self.patches(stack)
                self.plan.entries[0].action = action
                self.plan.entries[0].action = action
                if action == 'cached':
                    stack.enter_context(patch(
                        'wlre.services.official_bundle_download._verified_file',
                        return_value=False))
                with self.assertRaises(BundleRuntimeUnavailable):
                    load_verified_bundle_runtime(sync_root=self.root)
                self.plan.entries[0].action = 'cached'

    def test_invalid_textasset_reports_fixed_stage_not_private_error(self):
        with ExitStack() as stack:
            self.patches(stack)
            stack.enter_context(patch(
                'wlre.services.world.npc_talk.parse_talk_data',
                side_effect=ValueError('C:\\\\private\\\\account.txt')))
            with self.assertRaises(BundleRuntimeUnavailable) as context:
                load_verified_bundle_runtime(sync_root=self.root)
        self.assertIn('TalkData_C', str(context.exception))
        self.assertNotIn('private', str(context.exception))

    def test_wrong_pinned_manifest_and_wrong_baseline_fail_closed(self):
        with ExitStack() as stack:
            self.patches(stack)
            self.verified['DataPackage'].cache_path.write_bytes(b'tampered')
            with self.assertRaisesRegex(BundleRuntimeUnavailable, 'SHA-256'):
                load_verified_bundle_runtime(sync_root=self.root)
        self.verified['DataPackage'].cache_path.write_bytes(
            b'audited manifest fixture for DataPackage')
        self.supported['packages']['MainPackage']['manifest'] = (
            '1275_2026_10_23_18_29_38_49')
        with ExitStack() as stack:
            self.patches(stack)
            with self.assertRaisesRegex(BundleRuntimeUnavailable, 'Manifest'):
                load_verified_bundle_runtime(sync_root=self.root)

    def test_valid_pinned_bundles_work_even_if_candidate_failed(self):
        # Regression for Windows: Launcher four-candidate status can be
        # 'error' when its optional Eve decoder refuses another schema.
        # It must not gate the independently audited full Bundle runtime.
        self.receipt['status'] = 'error'
        with ExitStack() as stack:
            self.patches(stack)
            status = stack.enter_context(patch(
                'wlre.services.world.launcher_catalog.read_launcher_status',
                side_effect=AssertionError('optional status must not be read')))
            candidate = stack.enter_context(patch(
                'wlre.services.world.auto_catalog._trusted_cached_candidate',
                side_effect=AssertionError('optional candidate must not be read')))
            source = load_verified_bundle_runtime(sync_root=self.root)
        self.assertEqual(len(source.recipes), 1032)
        status.assert_not_called()
        candidate.assert_not_called()

    def test_schema_error_refuses_partial_data_activation(self):
        with ExitStack() as stack:
            self.patches(stack)
            self.recipes.pop(1032)
            with self.assertRaises(BundleRuntimeUnavailable):
                load_verified_bundle_runtime(sync_root=self.root)

    def test_runtime_uses_verified_bundle_when_no_legacy_zips(self):
        from wlre.services.world.runtime_1275 import _default_runtime
        _default_runtime.cache_clear()
        self.addCleanup(_default_runtime.cache_clear)
        formal = self.root / 'formal'
        data, eve = formal / '1275_DataCatalog.zip', formal / '1275_EveNpcIndex.zip'
        working = object()
        with patch('wlre.services.world.runtime_1275._paths',
                   return_value=(data, eve)), patch(
             'wlre.services.world.bundle_runtime_1275.load_verified_bundle_runtime',
             return_value=working) as bundle, patch(
             'wlre.services.world.preview_1275.load_preview') as legacy:
            self.assertIs(_default_runtime(), working)
            bundle.assert_called_once_with()
            legacy.assert_not_called()

    def test_partial_old_zip_does_not_block_independently_verified_bundle(self):
        from wlre.services.world.runtime_1275 import _default_runtime
        _default_runtime.cache_clear()
        self.addCleanup(_default_runtime.cache_clear)
        formal = self.root / 'formal'
        formal.mkdir()
        data, eve = formal / '1275_DataCatalog.zip', formal / '1275_EveNpcIndex.zip'
        data.write_bytes(b'old broken partial zip')
        working = object()
        with patch('wlre.services.world.runtime_1275._paths',
                   return_value=(data, eve)), patch(
             'wlre.services.world.bundle_runtime_1275.load_verified_bundle_runtime',
             return_value=working) as bundle, patch(
             'wlre.services.world.preview_1275.load_preview') as legacy:
            self.assertIs(_default_runtime(), working)
            bundle.assert_called_once_with()
            legacy.assert_not_called()
        self.assertEqual(data.read_bytes(), b'old broken partial zip')

    def test_two_invalid_old_zips_do_not_block_verified_bundle(self):
        from wlre.services.world.runtime_1275 import _default_runtime
        _default_runtime.cache_clear()
        self.addCleanup(_default_runtime.cache_clear)
        formal = self.root / 'formal'
        formal.mkdir()
        data, eve = formal / '1275_DataCatalog.zip', formal / '1275_EveNpcIndex.zip'
        data.write_bytes(b'old invalid data')
        eve.write_bytes(b'old invalid eve')
        working = object()
        with patch('wlre.services.world.runtime_1275._paths',
                   return_value=(data, eve)), patch(
             'wlre.services.world.preview_1275.load_preview',
             side_effect=ValueError('Bad legacy manifest')) as legacy, patch(
             'wlre.services.world.bundle_runtime_1275.load_verified_bundle_runtime',
             return_value=working) as bundle:
            self.assertIs(_default_runtime(), working)
            legacy.assert_called_once_with(data, eve)
            bundle.assert_called_once_with()
        self.assertEqual(eve.read_bytes(), b'old invalid eve')

    def test_legacy_decompression_error_uses_independently_pinned_bundle(self):
        import zlib
        from wlre.services.world.runtime_1275 import _default_runtime
        _default_runtime.cache_clear()
        self.addCleanup(_default_runtime.cache_clear)
        formal = self.root / 'formal'
        formal.mkdir()
        data, eve = formal / '1275_DataCatalog.zip', formal / '1275_EveNpcIndex.zip'
        data.write_bytes(b'old corrupt data')
        eve.write_bytes(b'old corrupt eve')
        working = object()
        with patch('wlre.services.world.runtime_1275._paths',
                   return_value=(data, eve)), patch(
             'wlre.services.world.preview_1275.load_preview',
             side_effect=zlib.error('corrupted gzip')), patch(
             'wlre.services.world.bundle_runtime_1275.load_verified_bundle_runtime',
             return_value=working):
            self.assertIs(_default_runtime(), working)

    def test_good_legacy_zips_still_take_priority_over_bundle(self):
        from wlre.services.world.runtime_1275 import _default_runtime
        _default_runtime.cache_clear()
        self.addCleanup(_default_runtime.cache_clear)
        formal = self.root / 'formal'
        formal.mkdir()
        data, eve = formal / '1275_DataCatalog.zip', formal / '1275_EveNpcIndex.zip'
        data.write_bytes(b'data fixture')
        eve.write_bytes(b'eve fixture')
        working = object()
        with patch('wlre.services.world.runtime_1275._paths',
                   return_value=(data, eve)), patch(
             'wlre.services.world.preview_1275.load_preview',
             return_value=working) as legacy, patch(
             'wlre.services.world.bundle_runtime_1275.load_verified_bundle_runtime'
         ) as bundle:
            self.assertIs(_default_runtime(), working)
            legacy.assert_called_once_with(data, eve)
            bundle.assert_not_called()

    def test_invalid_legacy_and_unverified_bundle_both_refused_without_writes(self):
        from wlre.services.world.runtime_1275 import (
            Runtime1275Unavailable, _default_runtime)
        _default_runtime.cache_clear()
        self.addCleanup(_default_runtime.cache_clear)
        from wlre.services.world.bundle_runtime_1275 import BundleRuntimeUnavailable
        formal = self.root / 'formal'
        formal.mkdir()
        data, eve = formal / '1275_DataCatalog.zip', formal / '1275_EveNpcIndex.zip'
        data.write_bytes(b'bad data')
        eve.write_bytes(b'bad eve')
        with patch('wlre.services.world.runtime_1275._paths',
                   return_value=(data, eve)), patch(
             'wlre.services.world.preview_1275.load_preview',
             side_effect=ValueError('bad legacy zip')), patch(
             'wlre.services.world.bundle_runtime_1275.load_verified_bundle_runtime',
             side_effect=BundleRuntimeUnavailable('仍缺少官方 Bundle：Eve')):
            with self.assertRaisesRegex(Runtime1275Unavailable, '缺少官方 Bundle：Eve'):
                _default_runtime()
        self.assertEqual(data.read_bytes(), b'bad data')
        self.assertEqual(eve.read_bytes(), b'bad eve')


if __name__ == '__main__':
    unittest.main()
