"""Offline activation tests: audited .bytes/.hash + Bundles, never manual ZIPs."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from wlre.services.world.bundle_runtime_1275 import (
    BundleRuntimeUnavailable, load_verified_bundle_runtime)


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
                spec=SimpleNamespace(package=package, package_version=version),
                cache_path=path, hash_text='ab12cd34')
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
                'SmithData_C', 'ScenesData_C')}
        self.items = {i: {'name': f'物品{i}', 'open_used': 0} for i in range(1, 1033)}
        self.recipes = {
            i: {'item_id': i, 'tool_id': 39053, 'output': 1,
                'materials': [], 'seconds': 1, 'order': i,
                'design_id': 0, 'time_id': 0, 'limit_kind': 0}
            for i in range(1, 1033)}
        self.scenes = {str(10000+i): [] for i in range(1262)}
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
            'wlre.services.instance_catalog.parse_stages',
            return_value={10000: {}}))
        stack.enter_context(patch(
            'wlre.services.world.doors_1275.parse_doors_1275',
            return_value={}))

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
        self.assertEqual(self.extract.call_count, 6)

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

    def test_wrong_pinned_manifest_and_wrong_launcher_state_fail_closed(self):
        with ExitStack() as stack:
            self.patches(stack)
            self.verified['DataPackage'].cache_path.write_bytes(b'tampered')
            with self.assertRaisesRegex(BundleRuntimeUnavailable, 'SHA-256'):
                load_verified_bundle_runtime(sync_root=self.root)
        self.verified['DataPackage'].cache_path.write_bytes(
            b'audited manifest fixture for DataPackage')
        self.receipt['status'] = 'error'
        with ExitStack() as stack:
            self.patches(stack)
            with self.assertRaises(BundleRuntimeUnavailable):
                load_verified_bundle_runtime(sync_root=self.root)

    def test_schema_error_refuses_partial_data_activation(self):
        with ExitStack() as stack:
            self.patches(stack)
            self.recipes.pop(1032)
            with self.assertRaises(BundleRuntimeUnavailable):
                load_verified_bundle_runtime(sync_root=self.root)

    def test_real_runtime_falls_back_only_if_both_manual_zips_absent(self):
        from wlre.services.world.runtime_1275 import _default_runtime
        _default_runtime.cache_clear()
        self.addCleanup(_default_runtime.cache_clear)
        zip_root = self.root / 'formal'
        data = zip_root / '1275_DataCatalog.zip'
        eve = zip_root / '1275_EveNpcIndex.zip'
        actual = object()
        with patch('wlre.services.world.runtime_1275._paths',
                   return_value=(data, eve)), patch(
             'wlre.services.world.bundle_runtime_1275.load_verified_bundle_runtime',
             return_value=actual) as build:
            self.assertIs(_default_runtime(), actual)
            build.assert_called_once_with()
        _default_runtime.cache_clear()
        zip_root.mkdir(parents=True)
        data.write_bytes(b'partial')
        with patch('wlre.services.world.runtime_1275._paths',
                   return_value=(data, eve)), patch(
             'wlre.services.world.bundle_runtime_1275.load_verified_bundle_runtime'
        ) as build:
            from wlre.services.world.runtime_1275 import Runtime1275Unavailable
            with self.assertRaises(Runtime1275Unavailable):
                _default_runtime()
            build.assert_not_called()


if __name__ == '__main__':
    unittest.main()
