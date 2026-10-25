"""Offline automatic data-compatibility verdict, independently of game protocol."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from wlre.services.world.auto_catalog import _ASSET_ROOT, _SOURCE_MAP
from wlre.services.world.catalog_adapters import FEATURES, SourceContract
from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
from wlre.services.world.catalog_compatibility import (
    CompatibilityError, assess_candidate, read_compatibility_report,
    write_compatibility_report,
)
from wlre.services.world.official_catalog_pipeline import AssetBinding, ResolvedAsset


class CompatibilityAssessmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.identity = OfficialCatalogIdentity(
            '1.3.21', '1.3.21',
            (PackageRevision('DataPackage', '1275_2026_10_21_18_27_33_84',
                             'a' * 64, '12345678'),
             PackageRevision('MainPackage', '1275_2026_10_21_18_29_38_49',
                             'b' * 64, 'abcdef01')))
        self.raws = {
            'npc': json.dumps({'schema_version': 1, 'source': 'EventData.NewNpc',
                               'record_count': 0, 'scenes': {}}).encode(),
            'shops': json.dumps({'schema_version': 1, 'source': 'EventData.NewInteract',
                                 'record_count': 0, 'scenes': {}}).encode(),
            'crafting': struct.pack('<i', 0),
            'scenes': struct.pack('<i', 0),
        }
        self.sources = tuple(
            ResolvedAsset(
                AssetBinding(
                    _ASSET_ROOT + _SOURCE_MAP[feature][0],
                    SourceContract(
                        feature, _SOURCE_MAP[feature][1], _SOURCE_MAP[feature][2],
                        '0' * 64, 'DataPackage',
                        '1275_2026_10_21_18_27_33_84'),
                    tuple(_ASSET_ROOT + name for name in _SOURCE_MAP[feature][3])),
                feature + '.bundle')
            for feature in FEATURES)
        self.metadata = {
            'catalog_key': self.identity.key,
            'official_identity': self.identity.as_dict(),
            'status': 'review_required', 'approved': False,
            'assets_ready': False, 'can_send_packets': False,
            'features': {},
        }
        for src in self.sources:
            feature = src.binding.contract.feature
            raw = self.raws[feature]
            self.metadata['features'][feature] = {
                'package': src.binding.contract.package,
                'package_version': src.binding.contract.package_version,
                'source_name': src.binding.contract.source_name,
                'schema_id': src.binding.contract.schema_id,
                'asset_path': src.binding.asset_path,
                'related_asset_paths': list(src.binding.related_asset_paths),
                'record_count': 0, 'bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(),
            }

    def assess(self):
        return assess_candidate(
            self.identity, self.sources, raw_by_feature=self.raws,
            metadata=self.metadata)

    def test_all_four_features_pass_but_protocol_and_login_remain_unverified(self):
        result = self.assess()
        self.assertEqual(result['data_compatibility'], 'compatible')
        self.assertEqual(result['protocol_compatibility'], 'unverified')
        self.assertEqual(set(result['features']), set(FEATURES))
        self.assertTrue(result['requires_protocol_review'])
        self.assertIs(result['approved'], False)
        self.assertIs(result['assets_ready'], False)
        self.assertIs(result['can_send_packets'], False)

    def test_any_missing_feature_fails_closed(self):
        self.raws.pop('shops')
        with self.assertRaisesRegex(CompatibilityError, 'source set'):
            self.assess()

    def test_source_hash_forged_even_with_matching_bytes_rejected(self):
        self.metadata['features']['npc']['sha256'] = 'f' * 64
        with self.assertRaisesRegex(CompatibilityError, 'npc'):
            self.assess()

    def test_correct_hash_but_bad_parser_never_counts_as_compatible(self):
        raw = b'not-a-json-index'
        self.raws['npc'] = raw
        self.metadata['features']['npc']['sha256'] = hashlib.sha256(raw).hexdigest()
        self.metadata['features']['npc']['bytes'] = len(raw)
        with self.assertRaisesRegex(CompatibilityError, 'npc source schema'):
            self.assess()

    def test_new_official_revision_cannot_reuse_previous_candidate(self):
        self.metadata['official_identity']['packages'][0]['full_version'] = '1276'
        with self.assertRaisesRegex(CompatibilityError, 'identity'):
            self.assess()

    def test_wrong_assetpath_or_schema_never_fuzzy_matched(self):
        for field, value in [('asset_path', 'Assets/Other/Eve.bytes'),
                             ('schema_id', 'eve-npc-json-v2')]:
            with self.subTest(field=field):
                old = self.metadata['features']['npc'][field]
                self.metadata['features']['npc'][field] = value
                with self.assertRaisesRegex(CompatibilityError, 'npc'):
                    self.assess()
                self.metadata['features']['npc'][field] = old

    def test_count_mismatch_rejected(self):
        self.metadata['features']['npc']['record_count'] = 1
        with self.assertRaisesRegex(CompatibilityError, 'npc'):
            self.assess()

    def test_display_report_binds_to_current_candidate_bytes(self):
        directory = self.identity.private_catalog_dir(self.root)
        directory.mkdir(parents=True)
        candidate = directory / 'candidate.zip'
        candidate.write_bytes(b'a synthetic candidate for an offline report test')
        report = self.assess()
        write_compatibility_report(self.identity, report, candidate_root=self.root)
        loaded = read_compatibility_report(self.identity, candidate_root=self.root)
        self.assertEqual(loaded['data_compatibility'], 'compatible')
        self.assertEqual(loaded['candidate_zip_sha256'],
                         hashlib.sha256(candidate.read_bytes()).hexdigest())
        candidate.write_bytes(b'second, different synthetic candidate')
        self.assertIsNone(read_compatibility_report(self.identity, candidate_root=self.root))

    def test_report_cannot_activate_game_resources(self):
        directory = self.identity.private_catalog_dir(self.root)
        directory.mkdir(parents=True)
        (directory / 'candidate.zip').write_bytes(b'candidate')
        report = self.assess()
        for field in ('approved', 'assets_ready', 'can_send_packets'):
            with self.subTest(field=field):
                changed = dict(report, **{field: True})
                with self.assertRaises(CompatibilityError):
                    write_compatibility_report(
                        self.identity, changed, candidate_root=self.root)


if __name__ == '__main__':
    unittest.main()
