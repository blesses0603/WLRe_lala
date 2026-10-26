"""新快照管線：生成的非遊戲樣本與假傳輸，不宣稱官方或實機驗收。"""
import hashlib
import io
import json
import struct
import tempfile
import unittest
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch

from wlre.resources_runtime.official.compatibility import CompatibilityValidator
from wlre.resources_runtime.official.contracts import (
    SCENE_DEFINITIONS,
    ResourceRequirement,
    ResourceStatus,
)
from wlre.resources_runtime.official.gaps import ResourceGapAnalyzer
from wlre.resources_runtime.official.manager import (
    OfficialResourceManager,
    ResourceRefreshError,
)
from wlre.resources_runtime.official.snapshots import SnapshotError, SnapshotStore
from wlre.resources_runtime.official.source import ROOT
from wlre.resources_runtime.parsers.scenes import SceneFormatError, parse_scene_table
from wlre.resources_runtime.parsers.unity_textasset import (
    UnityTextAssetError,
    extract_exact_textasset,
)
from wlre.resources_runtime.parsers.yooasset import parse_manifest
from wlre.services.instance_catalog import parse_stages
from wlre.services.official_manifest_sync import ManifestSpec, VerifiedManifest

VERSION = '9876_2026_10_01_01_02_03_04'
SCENE_PATH = SCENE_DEFINITIONS.asset_path


def scene_source(*ids):
    rows = []
    for scene_id in ids:
        row = bytearray(76)
        struct.pack_into('<H', row, 0, scene_id)
        struct.pack_into('<I', row, 4, scene_id + 1000)
        struct.pack_into('<H', row, 8, 8000)
        row[21:26] = bytes((8, 2, 1, 3, 4))
        struct.pack_into('<HHH', row, 26, 256, 20, 10)
        struct.pack_into('<HH', row, 52, 6000, 4000)
        row[57:59] = bytes((25, 30))
        struct.pack_into('<HH', row, 59, 12, 34)
        rows.append(row)
    return struct.pack('<i', len(rows)) + b''.join(rows)


def unity_fixture():
    head = b'UnityFS\0' + struct.pack('>I', 6) + b'5.x.x\0' + b'2019.4.0f1\0'
    return head + struct.pack('>QIII', len(head) + 40, 20, 64, 0x40) + bytes(20)


def text(value):
    raw = value.encode()
    return struct.pack('<H', len(raw)) + raw


def manifest(package='DataPackage', *, body=None, asset=SCENE_PATH, encrypted=False):
    body = unity_fixture() if body is None else body
    return b''.join((
        struct.pack('<I', 0x00594F4F), text('2.2.5'), bytes(3), struct.pack('<ii', 1, 0),
        text('ScriptableBuildPipeline'), text(package), text(VERSION), text(''),
        struct.pack('<i', 1), text('synthetic'), text(asset), text('fixture-guid'),
        struct.pack('<Hi', 0, 0), struct.pack('<i', 1), text('synthetic_s.bundle'),
        struct.pack('<I', 0), text(hashlib.md5(body, usedforsecurity=False).hexdigest()),
        text(zlib.crc32(body).to_bytes(4, 'little').hex()),
        struct.pack('<qBHH', len(body), encrypted, 0, 0),
    ))


class Response(io.BytesIO):
    status = 200

    def __init__(self, url, body):
        super().__init__(body)
        self.url = url
        self.headers = {'Content-Length': str(len(body))}

    def geturl(self):
        return self.url


class Fixture:
    def __init__(self):
        self.calls = []
        self.raw = scene_source(11016, 12170)
        self.files = {ROOT + '/ResourcePath_PC.dat': json.dumps(
            [{'ExeVer': '2.0.0', 'DataVer': '9.8.7'}]).encode()}
        self.base = ROOT + '/9.8.7/ResourcesPC/AssetBundle/'
        for package in ('DataPackage', 'MainPackage'):
            raw = manifest(package)
            self.files[self.base + package + '.bytes'] = raw
            self.files[self.base + package + '.version'] = VERSION.encode()
            self.files[self.base + package + '.hash'] = zlib.crc32(raw).to_bytes(4, 'little').hex().encode()
        self.files[self.base + 'synthetic_s.bundle'] = unity_fixture()

    def open(self, req, timeout):
        self.calls.append(req.full_url)
        return Response(req.full_url, self.files[req.full_url])

    def loader(self, path):
        obj = SimpleNamespace(type=SimpleNamespace(name='TextAsset'),
                              read=lambda: SimpleNamespace(name='ScenesData_C', script=self.raw))
        return SimpleNamespace(container={SCENE_PATH: obj})

    def verified(self, **kwargs):
        raw = manifest(**kwargs)
        spec = ManifestSpec('9.8.7', 'DataPackage', VERSION)
        return VerifiedManifest(spec, parse_manifest(raw), '00000000', Path('/synthetic'), False)


class SceneAdapterTests(unittest.TestCase):
    def test_all_legacy_fields_and_source_offsets_preserved(self):
        raw = scene_source(11016, 12170)
        result = parse_scene_table(raw)
        self.assertEqual([dict(row) for row in result.records], list(parse_stages(raw).values()))
        self.assertEqual(dict(result.records[0]), {
            'id': 11016, 'name_id': 12016, 'model_id': 8000, 'max_members': 8,
            'min_members': 1, 'min_level': 20, 'time_minutes': 10, 'tag': 2,
            'room_capacity': 3, 'group': 4, 'flag': 256, 'pos_x_ratio': 25,
            'pos_y_ratio': 30, 'map_width': 6000, 'map_height': 4000,
            'small_offset_x': 12, 'small_offset_y': 34})
        self.assertEqual(result.source_range(1), (80, 76))
        self.assertEqual(result.source_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(parse_stages(bytearray(raw)), parse_stages(memoryview(raw)))
        with self.assertRaises(TypeError):
            result.records[0]['id'] = 2
        with self.assertRaises(IndexError):
            result.source_range(-1)

    def test_wrong_size_count_duplicates_and_trailing_bytes_fail_closed(self):
        for raw in (b'', bytes(3), struct.pack('<i', -1), struct.pack('<i', 20001),
                    scene_source(1)[:-1], scene_source(1) + b'\0', scene_source(1, 1)):
            with self.subTest(size=len(raw)), self.assertRaises(SceneFormatError):
                parse_scene_table(raw)

    def test_unknown_bytes_retained_by_source_digest_not_assumed_zero(self):
        raw = bytearray(scene_source(123))
        raw[4 + 32:4 + 52] = bytes(range(20))
        table = parse_scene_table(bytes(raw))
        self.assertEqual(table.source_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(table.records[0]['id'], 123)

    def test_virtual_scene_and_empty_index_have_distinct_validity(self):
        raw = bytearray(scene_source(10))
        raw[4 + 52:4 + 56] = bytes(4)
        self.assertIsNotNone(CompatibilityValidator().validate(SCENE_DEFINITIONS, bytes(raw)).table)
        self.assertEqual(CompatibilityValidator().validate(SCENE_DEFINITIONS, scene_source()).finding.status,
                         ResourceStatus.INVALID)

    def test_raw_textasset_api_requires_full_bounded_safe_asset_path(self):
        for value in ('ScenesData_C.bytes', 'Assets/../a.bytes', 'Assets/a?.bytes',
                      'Assets//a', 'Assets/a\\b', 'Assets/a\0'):
            with self.subTest(path=value), self.assertRaises(UnityTextAssetError):
                extract_exact_textasset(value, (Path('/never-opened'),))

    def test_legacy_map_audit_container_helper_remains_importable(self):
        from wlre.services.world.unity_textasset import _find_exact_container_object
        expected = object()
        self.assertIs(_find_exact_container_object({SCENE_PATH: expected}, SCENE_PATH), expected)


class GapAnalyzerTests(unittest.TestCase):
    def test_statuses_distinguish_missing_unknown_unsupported_and_invalid(self):
        analyzer = ResourceGapAnalyzer()
        fixture = Fixture()
        cases = (
            ({}, SCENE_DEFINITIONS, ResourceStatus.UNKNOWN),
            ({'DataPackage': object()}, SCENE_DEFINITIONS, ResourceStatus.INVALID),
            ({'DataPackage': fixture.verified(asset='Assets/Other.bytes')},
             SCENE_DEFINITIONS, ResourceStatus.MISSING),
            ({'DataPackage': fixture.verified()}, replace(SCENE_DEFINITIONS, parser_id='unknown'),
             ResourceStatus.UNSUPPORTED),
            ({'DataPackage': fixture.verified(encrypted=True)}, SCENE_DEFINITIONS,
             ResourceStatus.UNSUPPORTED),
        )
        with tempfile.TemporaryDirectory() as temp:
            for manifests, requirement, status in cases:
                with self.subTest(status=status):
                    report = analyzer.analyze((requirement,), manifests, bundle_cache=temp)
                    self.assertFalse(report.complete)
                    self.assertEqual(report.findings[0].status, status)

    def test_cycle_and_missing_bundle_are_invalid_not_downloaded(self):
        for dependency in ('synthetic_s.bundle', 'missing.bundle'):
            source = Fixture().verified()
            source.index['bundles'][0]['dependencies'] = [dependency]
            with tempfile.TemporaryDirectory() as temp:
                report = ResourceGapAnalyzer().analyze(
                    (SCENE_DEFINITIONS,), {'DataPackage': source}, bundle_cache=temp)
            self.assertEqual(report.findings[0].status, ResourceStatus.INVALID)

    def test_exact_binding_cannot_be_relabelled_with_supported_parser(self):
        wrong = replace(SCENE_DEFINITIONS, asset_path='Assets/Unreviewed.bytes')
        result = CompatibilityValidator().validate(wrong, scene_source(1))
        self.assertEqual(result.finding.status, ResourceStatus.UNSUPPORTED)
        for requirements in ([], (), (SCENE_DEFINITIONS,) * 2):
            with self.assertRaises(ValueError):
                ResourceGapAnalyzer().analyze(requirements, {})
        with self.assertRaises(ValueError):
            ResourceRequirement('../unsafe', 'scene', 'DataPackage', SCENE_PATH, 'parser')

    def test_aggregate_dependency_quota_prevents_any_candidate_activation(self):
        source = Fixture().verified()
        source.index['bundles'][0]['file_size'] = 64 * 1024 * 1024 + 1
        with tempfile.TemporaryDirectory() as temp:
            report = ResourceGapAnalyzer().analyze(
                (SCENE_DEFINITIONS,), {'DataPackage': source}, bundle_cache=temp)
        self.assertFalse(report.complete)
        self.assertEqual(report.findings[0].code, 'resource_scope_quota_exceeded')


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(self.temp.name)

    def test_content_addressed_cas_preserves_previous_receipt_and_no_current_claim(self):
        first = self.store.commit('scene', {'step': 1}, expected_current=None)
        second = self.store.commit('scene', {'step': 2}, expected_current=first)
        self.assertEqual(self.store.current_id('scene'), second)
        self.assertEqual(json.loads(self.store.read(first)), {'step': 1})
        with self.assertRaisesRegex(SnapshotError, 'changed_during_refresh'):
            self.store.commit('scene', {'step': 3}, expected_current=first)
        self.assertEqual(self.store.current_id('scene'), second)
        self.assertEqual(self.store.diagnose('scene')['status'], 'unverified_cache_diagnostic_only')

    def test_concurrent_publishers_have_exactly_one_winner(self):
        barrier = Barrier(2)
        def commit(step):
            barrier.wait(timeout=5)
            try:
                self.store.commit('scene', {'step': step}, expected_current=None)
                return 'committed'
            except SnapshotError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(executor.map(commit, (1, 2)), ['committed', 'conflict'])

    def test_tampered_blob_path_traversal_and_oversized_pointer_rejected(self):
        digest = self.store.put(b'original')
        (Path(self.temp.name) / 'objects' / digest).write_bytes(b'modified')
        with self.assertRaises(SnapshotError):
            self.store.read(digest)
        for invalid in ('../outside', 'a' * 63, 'A' * 64):
            with self.assertRaises(SnapshotError):
                self.store.read(invalid)
        with self.assertRaises(ValueError):
            self.store.current_id('../outside')
        pointer = Path(self.temp.name) / 'scopes' / 'scene.json'
        pointer.parent.mkdir()
        pointer.write_bytes(b' ' * 1025)
        with self.assertRaises(SnapshotError):
            self.store.current_id('scene')

    def test_partial_publication_failure_does_not_change_pointer(self):
        first = self.store.commit('scene', {'step': 1}, expected_current=None)
        with (
            patch('wlre.resources_runtime.official.snapshots.write_json', side_effect=OSError('disk full')),
            self.assertRaises(OSError),
        ):
            self.store.commit('scene', {'step': 2}, expected_current=first)
        self.assertEqual(self.store.current_id('scene'), first)
        self.assertFalse(list(Path(self.temp.name).rglob('*.partial')))

    def test_duplicate_pointer_keys_are_not_accepted(self):
        pointer = Path(self.temp.name) / 'scopes' / 'scene.json'
        pointer.parent.mkdir()
        pointer.write_text('{"snapshot":"' + 'a' * 64 + '","snapshot":"' + 'b' * 64 + '"}')
        with self.assertRaises(SnapshotError):
            self.store.current_id('scene')


class ResourceManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = Fixture()
        self.decoder = patch('wlre.resources_runtime.parsers.unity_textasset._loader',
                             side_effect=self.fixture.loader)
        self.decoder.start()
        self.addCleanup(self.decoder.stop)
        self.manager = OfficialResourceManager(self.temp.name, opener=self.fixture.open)
        self.addCleanup(self.manager.close)

    def refresh(self, **kwargs):
        return self.manager.refresh('2.0.0', scope='scene', requirements=(SCENE_DEFINITIONS,), **kwargs)

    def test_end_to_end_formal_manifest_transport_schema_and_atomic_snapshot(self):
        service = self.refresh()
        self.assertEqual(service.get('scene_definitions', 12170)['map_width'], 6000)
        self.assertIsNone(service.get('scene_definitions', 9999))
        self.assertFalse(service.protocol_approved)
        self.assertEqual(service.versions.data_version, '9.8.7')
        receipt = self.manager.diagnose('scene')['document']
        self.assertEqual(receipt['acceptance'], 'validated_requested_scope')
        self.assertEqual(len(receipt['manifests']), 2)
        self.assertEqual(receipt['sources'][0]['uninterpreted_ranges'][2], [32, 20])
        self.assertEqual(receipt['sources'][0]['unresolved_relations'], ['name_id', 'model_id'])
        self.assertEqual(receipt['sources'][0]['sha256'], hashlib.sha256(self.fixture.raw).hexdigest())
        with self.assertRaises(TypeError):
            service.records('scene_definitions')[0]['id'] = 42
        with self.assertRaises(ValueError):
            service.get('scene_definitions', True)
        self.assertEqual(self.fixture.calls.count(self.fixture.base + 'synthetic_s.bundle'), 1)

    def test_refresh_rechecks_official_metadata_but_reuses_verified_bytes(self):
        first = self.refresh()
        second = self.refresh()
        with self.assertRaisesRegex(ResourceRefreshError, 'revoked'):
            first.records('scene_definitions')
        self.assertEqual(len(second.records('scene_definitions')), 2)
        self.assertEqual(self.fixture.calls.count(self.fixture.base + 'synthetic_s.bundle'), 1)
        self.assertEqual(self.fixture.calls.count(self.fixture.base + 'DataPackage.bytes'), 1)
        self.assertEqual(self.fixture.calls.count(self.fixture.base + 'DataPackage.hash'), 4)

    def test_invalid_candidate_retains_previous_only_for_diagnostics(self):
        first = self.refresh()
        self.fixture.raw = scene_source(1, 1)
        with self.assertRaisesRegex(ResourceRefreshError, 'incompatible') as caught:
            self.refresh()
        self.assertEqual(caught.exception.findings[0].status, ResourceStatus.INVALID)
        self.assertEqual(self.manager.diagnose('scene')['snapshot'], first.snapshot_id)
        with self.assertRaises(ResourceRefreshError):
            first.records('scene_definitions')

    def test_offline_refresh_never_grants_cached_current_view(self):
        first = self.refresh()
        with (
            patch.object(self.manager._transport, 'read', side_effect=OSError('offline')),
            self.assertRaisesRegex(ResourceRefreshError, 'refresh_failed'),
        ):
            self.refresh()
        self.assertEqual(self.manager.diagnose('scene')['snapshot'], first.snapshot_id)
        with self.assertRaises(ResourceRefreshError):
            first.records('scene_definitions')

    def test_version_change_during_download_is_rejected(self):
        original = self.fixture.loader
        def changed(path):
            self.fixture.files[self.fixture.base + 'DataPackage.version'] = b'9877_2026_10_01_01_02_03_04'
            return original(path)
        with (
            patch('wlre.resources_runtime.parsers.unity_textasset._loader', side_effect=changed),
            self.assertRaisesRegex(ResourceRefreshError, 'versions_changed'),
        ):
            self.refresh()
        self.assertIsNone(self.manager.diagnose('scene'))

    def test_manifest_change_without_version_change_is_rejected(self):
        original = self.fixture.loader
        def changed(path):
            self.fixture.files[self.fixture.base + 'DataPackage.hash'] = b'00000000'
            return original(path)
        with (
            patch('wlre.resources_runtime.parsers.unity_textasset._loader', side_effect=changed),
            self.assertRaisesRegex(ResourceRefreshError, 'manifest_changed'),
        ):
            self.refresh()
        self.assertIsNone(self.manager.diagnose('scene'))

    def test_missing_requirement_downloads_no_bundles(self):
        wrong = replace(SCENE_DEFINITIONS, parser_id='unsupported')
        with self.assertRaises(ResourceRefreshError) as caught:
            self.manager.refresh('2.0.0', scope='scene', requirements=(wrong,))
        self.assertEqual(caught.exception.findings[0].status, ResourceStatus.UNSUPPORTED)
        self.assertFalse(any(url.endswith('.bundle') for url in self.fixture.calls))

    def test_cancel_close_and_reentrant_refresh_cannot_publish(self):
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            self.refresh(cancel_event=cancelled)
        self.assertEqual(self.fixture.calls, [])
        with (
            patch.object(self.manager, '_refresh', side_effect=lambda *args: self.refresh()),
            self.assertRaisesRegex(ResourceRefreshError, 'already_running'),
        ):
            self.refresh()
        self.manager.close()
        with self.assertRaises(InterruptedError):
            self.refresh()
        self.assertIsNone(self.manager.diagnose('scene'))

    def test_cancellation_inside_legacy_manifest_adapter_remains_interrupted(self):
        cancelled = Event()
        original = self.fixture.open
        def interrupt(req, timeout):
            response = original(req, timeout)
            if req.full_url.endswith('DataPackage.bytes'):
                cancelled.set()
            return response
        with (
            patch('wlre.services.official_manifest_sync.build_opener') as build,
            self.assertRaises(InterruptedError),
        ):
            # 真正走 Manifest 共用下載器；只有 HTTP 回應使用生成樣本。
            build.return_value.open = interrupt
            self.manager._opener = None
            self.refresh(cancel_event=cancelled)
        self.assertIsNone(self.manager.diagnose('scene'))

    def test_mid_decode_cancel_and_close_revoke_views_and_leave_previous(self):
        for close in (False, True):
            with self.subTest(close=close):
                first = self.refresh()
                cancelled = Event()
                original = self.fixture.loader
                def interrupt(path, close=close, cancelled=cancelled, original=original):
                    self.manager.close() if close else cancelled.set()
                    return original(path)
                with (
                    patch('wlre.resources_runtime.parsers.unity_textasset._loader', side_effect=interrupt),
                    self.assertRaises(InterruptedError),
                ):
                    self.refresh(cancel_event=cancelled)
                self.assertEqual(self.manager.diagnose('scene')['snapshot'], first.snapshot_id)
                with self.assertRaises(ResourceRefreshError):
                    first.records('scene_definitions')

    def test_bundle_integrity_error_keeps_snapshot_unchanged(self):
        first = self.refresh()
        for path in Path(self.temp.name).rglob('*.bundle'):
            path.write_bytes(b'corrupt cache')
        self.fixture.files[self.fixture.base + 'synthetic_s.bundle'] = b'wrong download'
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual(self.manager.diagnose('scene')['snapshot'], first.snapshot_id)

    def test_cache_rechecked_immediately_before_extraction(self):
        original = self.manager._transport.download
        def corrupt(*args, **kwargs):
            path = original(*args, **kwargs)
            path.write_bytes(b'changed after download')
            return path
        with (
            patch.object(self.manager._transport, 'download', side_effect=corrupt),
            self.assertRaisesRegex(ResourceRefreshError, 'bundle_cache_changed') as caught,
        ):
            self.refresh()
        self.assertEqual(caught.exception.findings[0].field, 'size_md5_crc32')
        self.assertEqual(caught.exception.findings[0].resource, SCENE_PATH)
        self.assertIsNone(self.manager.diagnose('scene'))


class SnapshotToolTests(unittest.TestCase):
    def test_private_cache_rejects_actual_project_and_unconfirmed_git_errors(self):
        from tools.check_official_resource_snapshot import private_cache
        with self.assertRaises(ValueError):
            private_cache(Path(__file__).resolve().parents[1] / 'private-assets')
        with (
            tempfile.TemporaryDirectory() as temp,
            patch('tools.check_official_resource_snapshot.subprocess.run', return_value=SimpleNamespace(
                returncode=128, stderr=b'fatal: not a git repository (or any parent)')),
        ):
            self.assertEqual(private_cache(Path(temp) / 'new-cache'), Path(temp).resolve() / 'new-cache')
        for result in (SimpleNamespace(returncode=0, stderr=b''),
                       SimpleNamespace(returncode=128, stderr=b'permission denied')):
            with (
                patch('tools.check_official_resource_snapshot.subprocess.run', return_value=result),
                self.assertRaises(ValueError),
            ):
                private_cache(Path(temp))
