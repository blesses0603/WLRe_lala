"""合成樣本驗證引用語意／失敗界線；不代替官方遊戲驗收。"""
import hashlib
import struct
import tempfile
import unittest
import zlib
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import patch

from test_official_resource_manager import (
    VERSION,
    Fixture,
    scene_source,
    text,
    unity_fixture,
)

from wlre.network.wire import ProtocolError
from wlre.resources_runtime.official.compatibility import CompatibilityValidator
from wlre.resources_runtime.official.contracts import (
    SCENE_DEFINITIONS,
    TEXT_DEFINITIONS,
    ResourceStatus,
)
from wlre.resources_runtime.official.manager import (
    OfficialResourceManager,
    ResourceRefreshError,
)
from wlre.resources_runtime.official.references import (
    audit_scene_references,
    reference_summary,
)
from wlre.resources_runtime.parsers.scenes import parse_scene_table
from wlre.resources_runtime.parsers.texts import TextFormatError, parse_text_table
from wlre.services.expedition.data import parse_text_data
from wlre.services.world.scene_names_1275 import bind_scene_names


def text_source(*records):
    result = struct.pack('<i', len(records))
    for key, value in records:
        raw = value.encode('utf-16-le')
        result += struct.pack('<IH', key, len(raw)) + raw
    return result


def verified_main(*assets, encrypted=False):
    fixture = Fixture().verified()
    spec = replace(fixture.spec, package='MainPackage')
    index = {**fixture.index,
             'header': {**fixture.index['header'], 'package_name': 'MainPackage'},
             'assets': list(assets),
             'bundles': [{**fixture.index['bundles'][0], 'encrypted': encrypted}]}
    return replace(fixture, spec=spec, index=index)


def model_asset(model_id=8000, family='BaseScenes', **changes):
    return {'address': f'M{model_id:05}',
            'path': f'Assets/ResourcesBuild/Scenes/{family}/M{model_id:05}/M{model_id:05}.unity',
            'bundle_name': 'synthetic_s.bundle', **changes}


class TextAdapterTests(unittest.TestCase):
    def test_offsets_unicode_immutability_and_old_api(self):
        raw = text_source((100, '測試😀'), (101, ''))
        table = parse_text_table(raw)
        self.assertEqual(parse_text_data(raw), {100: '測試😀', 101: ''})
        self.assertEqual(table.source_range(0), (4, 14))
        self.assertEqual(table.source_range(1), (18, 6))
        self.assertEqual(table.source_sha256, hashlib.sha256(raw).hexdigest())
        with self.assertRaises(TypeError):
            table.records[0]['text'] = 'changed'
        for index in (-1, 2, True):
            with self.subTest(index=index), self.assertRaises(IndexError):
                table.source_range(index)

    def test_malformed_input_and_legacy_error_type(self):
        examples = (b'', bytes(4), struct.pack('<i', -1), text_source((1, 'a'))[:-1],
                    text_source((1, 'a')) + b'\0', text_source((1, 'a'), (1, 'b')),
                    struct.pack('<iIH', 1, 1, 1) + b'x',
                    struct.pack('<iIH', 1, 1, 2) + b'\0\xd8', bytearray(text_source((1, 'a'))))
        for raw in examples:
            with self.subTest(raw_type=type(raw).__name__, size=len(raw)):
                with self.assertRaises(TextFormatError):
                    parse_text_table(raw)
                with self.assertRaises(ProtocolError):
                    parse_text_data(raw)

    def test_adapter_exact_binding_and_variable_record_receipt(self):
        raw = text_source((1, 'a'))
        result = CompatibilityValidator().validate(TEXT_DEFINITIONS, raw)
        self.assertEqual(result.finding.status, ResourceStatus.VALID)
        self.assertEqual(CompatibilityValidator().validate(
            replace(TEXT_DEFINITIONS, asset_path='Assets/Other.bytes'), raw).finding.status,
            ResourceStatus.UNSUPPORTED)


class SceneReferenceTests(unittest.TestCase):
    def audit(self, main=None, texts=None, raw=None):
        scenes = parse_scene_table(scene_source(11016) if raw is None else raw)
        return audit_scene_references(scenes, texts, main or verified_main(model_asset()))

    def test_scene_id_model_id_name_id_remain_separate(self):
        rows = self.audit(texts=parse_text_table(text_source((12016, '  官方場景  '))))
        row = rows[0]
        self.assertEqual((row.scene_id, row.model_id, row.name_id), (11016, 8000, 12016))
        self.assertEqual(row.name, '官方場景')
        self.assertEqual(row.name_status, ResourceStatus.VALID)
        self.assertEqual(row.model_manifest_status, ResourceStatus.VALID)
        self.assertEqual(row.model_content_status, ResourceStatus.UNKNOWN)
        self.assertFalse(row.geometry_ready)
        with self.assertRaises(FrozenInstanceError):
            row.name = 'wrong'
        summary = reference_summary(rows)
        self.assertFalse(summary['geometry_ready'])
        self.assertEqual(summary['name_statuses'], {'VALID': 1})

    def test_names_are_unknown_missing_or_invalid_without_fallback(self):
        for raw, status in ((None, ResourceStatus.UNKNOWN),
                            (text_source((999, '別的名稱')), ResourceStatus.MISSING),
                            (text_source((12016, '')), ResourceStatus.INVALID),
                            (text_source((12016, 'a\nb')), ResourceStatus.INVALID),
                            (text_source((12016, 'x' * 161)), ResourceStatus.INVALID)):
            with self.subTest(status=status):
                row = self.audit(texts=None if raw is None else parse_text_table(raw))[0]
                self.assertEqual(row.name_status, status)
                self.assertIsNone(row.name)

    def test_zero_name_reference_is_not_resolved_from_text_zero(self):
        raw = bytearray(scene_source(11016))
        struct.pack_into('<I', raw, 8, 0)
        table = parse_text_table(text_source((0, '錯誤零號名稱')))
        self.assertEqual(self.audit(texts=table, raw=bytes(raw))[0].name_status, ResourceStatus.MISSING)
        self.assertEqual(bind_scene_names({11016: {'name_id': 0}}, {0: '錯誤零號名稱'}), {})

    def test_missing_model_is_preserved_not_replaced_with_scene_id(self):
        row = self.audit(main=verified_main(model_asset(11016)))[0]
        self.assertEqual(row.model_manifest_status, ResourceStatus.MISSING)
        self.assertIsNone(row.model_asset_path)
        self.assertEqual(reference_summary((row,))['missing_distinct_models'], 1)

    def test_address_and_path_identity_must_agree(self):
        for asset in (model_asset(address='M11016'),
                      model_asset(path='Assets/Unknown/M08000.unity'),
                      model_asset(address=''), model_asset(bundle_name='missing.bundle')):
            with self.subTest(asset=asset):
                self.assertEqual(self.audit(main=verified_main(asset))[0].model_manifest_status,
                                 ResourceStatus.INVALID)

    def test_duplicate_model_identity_is_not_deduplicated_by_name(self):
        main = verified_main(model_asset(), model_asset(family='StageScenes'))
        self.assertEqual(self.audit(main=main)[0].model_code, 'scene_model_identity_ambiguous')

    def test_encrypted_model_not_approved(self):
        row = self.audit(main=verified_main(model_asset(), encrypted=True))[0]
        self.assertEqual(row.model_manifest_status, ResourceStatus.UNSUPPORTED)

    def test_main_package_identity_is_required(self):
        with self.assertRaises(ValueError):
            self.audit(main=Fixture().verified())


def combined_manifest():
    body = unity_fixture()
    assets = b''.join(text('synthetic') + text(path) + text('fixture-guid') + struct.pack('<Hi', 0, 0)
                      for path in (SCENE_DEFINITIONS.asset_path, TEXT_DEFINITIONS.asset_path))
    return b''.join((
        struct.pack('<I', 0x00594F4F), text('2.2.5'), bytes(3), struct.pack('<ii', 1, 0),
        text('ScriptableBuildPipeline'), text('DataPackage'), text(VERSION), text(''),
        struct.pack('<i', 2), assets, struct.pack('<i', 1), text('synthetic_s.bundle'),
        struct.pack('<I', 0), text(hashlib.md5(body, usedforsecurity=False).hexdigest()),
        text(zlib.crc32(body).to_bytes(4, 'little').hex()), struct.pack('<qBHH', len(body), 0, 0, 0)))


class ReferencePipelineTests(unittest.TestCase):
    def fixture(self, raw_text=None):
        fixture = Fixture()
        raw = combined_manifest()
        fixture.files[fixture.base + 'DataPackage.bytes'] = raw
        fixture.files[fixture.base + 'DataPackage.hash'] = zlib.crc32(raw).to_bytes(4, 'little').hex().encode()
        raw_text = text_source((12016, '官方甲'), (13170, '官方乙')) if raw_text is None else raw_text
        sources = {SCENE_DEFINITIONS.asset_path: fixture.raw, TEXT_DEFINITIONS.asset_path: raw_text}

        def loader(path):
            return SimpleNamespace(container={path: SimpleNamespace(type=SimpleNamespace(name='TextAsset'),
                read=lambda data=data, path=path: SimpleNamespace(
                    name=path.rsplit('/', 1)[1].removesuffix('.bytes'), script=data))
                for path, data in sources.items()})
        return fixture, loader

    def test_atomic_two_source_snapshot_with_separate_receipts_and_revocation(self):
        fixture, loader = self.fixture()
        with tempfile.TemporaryDirectory() as root, patch(
                'wlre.resources_runtime.parsers.unity_textasset._loader', loader):
            manager = OfficialResourceManager(root, opener=fixture.open)
            service = manager.refresh('2.0.0', scope='references',
                                      requirements=(SCENE_DEFINITIONS, TEXT_DEFINITIONS))
            self.assertEqual(service.scene_reference(11016).name, '官方甲')
            self.assertEqual(service.scene_reference(12170).name, '官方乙')
            self.assertEqual(service.reference_summary()['model_manifest_statuses'], {'MISSING': 2})
            sources = manager.diagnose('references')['document']['sources']
            self.assertEqual([row['record_size'] for row in sources], [76, None])
            self.assertEqual([row['acceptance_scope'] for row in sources],
                             ['scene_definitions_only', 'text_definitions_only'])
            self.assertEqual(fixture.calls.count(fixture.base + 'synthetic_s.bundle'), 1)
            self.assertFalse(service.protocol_approved)
            self.assertIsNone(service.scene_reference(65535))
            with self.assertRaises(ValueError):
                service.scene_reference(True)
            manager.close()
            for query in (lambda: service.scene_reference(11016), service.reference_summary):
                with self.assertRaises(ResourceRefreshError):
                    query()

    def test_invalid_text_does_not_publish_partial_snapshot(self):
        fixture, loader = self.fixture(b'bad')
        with (tempfile.TemporaryDirectory() as root,
              patch('wlre.resources_runtime.parsers.unity_textasset._loader', loader),
              OfficialResourceManager(root, opener=fixture.open) as manager):
            with self.assertRaises(ResourceRefreshError):
                manager.refresh('2.0.0', scope='references',
                                requirements=(SCENE_DEFINITIONS, TEXT_DEFINITIONS))
            self.assertIsNone(manager.diagnose('references'))
