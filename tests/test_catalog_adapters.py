"""Offline synthetic tests. No CDN, game binaries, credentials or network packets."""
import hashlib
import json
import struct
import unittest

from wlre.services.world.catalog_adapters import (
    CatalogAdapterError, SourceContract, parse_feature, parse_selected,
)

KEY = 'a' * 64
REV = '1275_2026_10_21_18_27_33_84'
FUTURE = '1300_2027_01_01_00_00_00_00'


def blob(source, scenes):
    count = sum(len(rows) for rows in scenes.values())
    return json.dumps({'schema_version': 1, 'source': source, 'scenes': scenes,
                       'record_count': count}, separators=(',', ':')).encode()


def contract(feature, schema, raw, version=REV, name='Eve'):
    return SourceContract(feature, name, schema, hashlib.sha256(raw).hexdigest(),
                          'DataPackage', version)


class AdapterTests(unittest.TestCase):
    def test_npc_read_only_and_no_fixed_1275_runtime_assumption(self):
        raw = blob('EventData.NewNpc', {'100': [
            {'index': 3, 'npc_id': 42, 'x': 150, 'y': 200}]})
        for revision in (REV, FUTURE):
            with self.subTest(revision=revision):
                c = contract('npc', 'eve-npc-json-v1', raw, version=revision)
                result = parse_feature(catalog_key=KEY,
                                       package_versions={'DataPackage': revision},
                                       contract=c, raw=raw)
                self.assertEqual(result.record_count, 1)
                self.assertEqual(result.records['100'][0]['npc_id'], 42)
                self.assertFalse(result.can_send_packets)
                self.assertFalse(result.assets_ready)

    def test_shop_index_read_only(self):
        raw = blob('EventData.NewInteract', {'100': [{'index': 7,
            'form_kind': 3, 'items': [{'id': 1, 'text_id': 68,
                                      'database_kind': 2, 'kind': 3}]}]})
        result = parse_feature(catalog_key=KEY,
                               package_versions={'DataPackage': REV},
                               contract=contract('shops', 'eve-interact-json-v1', raw),
                               raw=raw)
        self.assertEqual(result.record_count, 1)
        self.assertFalse(result.can_send_packets)

    def test_reject_changed_payload_even_when_schema_is_same(self):
        raw = blob('EventData.NewNpc', {'1': []})
        c = contract('npc', 'eve-npc-json-v1', raw)
        with self.assertRaisesRegex(CatalogAdapterError, 'SHA-256'):
            parse_feature(catalog_key=KEY, package_versions={'DataPackage': REV},
                          contract=c, raw=raw + b' ')

    def test_unknown_schema_and_path_escape(self):
        raw = blob('EventData.NewNpc', {'1': []})
        for schema in ('fixed-1275-offset', 'unsupported-v2'):
            with self.assertRaises(CatalogAdapterError):
                contract('npc', schema, raw)
        with self.assertRaises(CatalogAdapterError):
            SourceContract('npc', '../Eve', 'eve-npc-json-v1',
                           hashlib.sha256(raw).hexdigest(), 'DataPackage', REV)

    def test_duplicate_event_index_fail_closed(self):
        raw = blob('EventData.NewNpc', {'1': [
            {'index': 0, 'npc_id': 1, 'x': 2, 'y': 3},
            {'index': 0, 'npc_id': 4, 'x': 5, 'y': 6}]})
        with self.assertRaisesRegex(CatalogAdapterError, 'duplicate'):
            parse_feature(catalog_key=KEY, package_versions={'DataPackage': REV},
                          contract=contract('npc', 'eve-npc-json-v1', raw), raw=raw)

    def test_wrong_schema_source_and_count_rejected(self):
        raw = blob('EventData.NewInteract', {'1': []})
        with self.assertRaisesRegex(CatalogAdapterError, 'source mismatch'):
            parse_feature(catalog_key=KEY, package_versions={'DataPackage': REV},
                          contract=contract('npc', 'eve-npc-json-v1', raw), raw=raw)
        doc = json.loads(blob('EventData.NewNpc', {'1': []}))
        doc['record_count'] = 9
        wrong = json.dumps(doc).encode()
        with self.assertRaisesRegex(CatalogAdapterError, 'count mismatch'):
            parse_feature(catalog_key=KEY, package_versions={'DataPackage': REV},
                          contract=contract('npc', 'eve-npc-json-v1', wrong), raw=wrong)

    def test_wrong_package_revision_rejected(self):
        raw = blob('EventData.NewNpc', {'1': []})
        with self.assertRaisesRegex(CatalogAdapterError, 'revision mismatch'):
            parse_feature(catalog_key=KEY, package_versions={'DataPackage': FUTURE},
                          contract=contract('npc', 'eve-npc-json-v1', raw), raw=raw)

    def test_binary_layout_size_must_be_exact(self):
        for feature, schema, size in (
            ('crafting', 'smith-new-33-v1', 33),
            ('scenes', 'stage-new-76-v1', 76),
        ):
            raw = struct.pack('<i', 1) + bytes(size - 1)
            with self.subTest(feature=feature), self.assertRaisesRegex(
                    CatalogAdapterError, 'layout'):
                parse_feature(catalog_key=KEY, package_versions={'DataPackage': REV},
                              contract=contract(feature, schema, raw), raw=raw)

    def test_invalid_empty_and_oversized_source(self):
        c = SourceContract('npc', 'Eve', 'eve-npc-json-v1', '0'*64,
                           'DataPackage', REV)
        for raw in (b'', b'0' * (16*1024*1024 + 1)):
            with self.assertRaisesRegex(CatalogAdapterError, 'oversized'):
                parse_feature(catalog_key=KEY, package_versions={'DataPackage': REV},
                              contract=c, raw=raw)

    def test_selected_requires_every_feature_before_returning(self):
        raw = blob('EventData.NewNpc', {'1': []})
        with self.assertRaisesRegex(CatalogAdapterError, 'All four'):
            parse_selected(catalog_key=KEY,
                           package_versions={'DataPackage': REV},
                           contracts={'npc': contract('npc','eve-npc-json-v1', raw)},
                           source_payloads={'Eve': raw})


if __name__ == '__main__':
    unittest.main()
