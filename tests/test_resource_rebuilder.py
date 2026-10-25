"""Offline tests of incremental raw asset rebuilding, retaining existing files."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib
from zipfile import ZipFile

from wlre.services.official_manifest_sync import ManifestSpec, VerifiedManifest
from wlre.services.official_bundle_download import spec_from_manifest
from wlre.services.resource_compatibility import load_supported_resources
from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
from wlre.services.world.resource_rebuilder import (
    rebuild_raw_resources, ResourceRebuildError, _load_previous,
)


class RawRebuilderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.candidates = self.home / 'derived'
        self.bundles = self.home / 'bundles'
        supported = load_supported_resources()
        self.revision = supported['packages']['DataPackage']['manifest']
        main = supported['packages']['MainPackage']['manifest']
        self.identity = OfficialCatalogIdentity(
            '1.3.21', '1.3.0', (
                PackageRevision('DataPackage', self.revision, 'a'*64, '12345678'),
                PackageRevision('MainPackage', main, 'b'*64, 'abcdef12')))
        self.payloads = {
            'datapackage_data_a.bundle': b'fake UnityFS alpha payload',
            'datapackage_data_b.bundle': b'fake UnityFS beta payload',
        }
        self.paths = {
            'Assets/ResourcesBuild/Data/AlphaData_C.bytes':
                'datapackage_data_a.bundle',
            'Assets/ResourcesBuild/Data/TalkData_C.bytes':
                'datapackage_data_b.bundle',
        }
        self.index = {
            'header': {'package_name':'DataPackage',
                       'package_version':self.revision,
                       'file_version':'2.2.5','output_name_style':1},
            'assets': [{'path': k, 'bundle_name': v}
                       for k, v in self.paths.items()],
            'bundles': [
                {'name': name, 'file_size':len(body),
                 'file_hash': hashlib.md5(body).hexdigest(),
                 'file_crc': (zlib.crc32(body)&0xffffffff).to_bytes(
                     4,'little').hex(), 'dependencies':[]}
                for name, body in self.payloads.items()],
        }
        self.manifest = VerifiedManifest(
            ManifestSpec('1.3.21','DataPackage',self.revision),
            self.index,'12345678',self.home/'DataPackage.bytes', False)
        self.reads = []
        self.requests = []

    def fetch(self, spec, *, cache_root):
        self.requests.append(spec.name)
        target = spec.cache_path(cache_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.payloads[spec.name])
        return target

    def extract(self, binding, paths):
        self.reads.append(binding.asset_path)
        return b'raw:' + binding.asset_path.encode()

    def rebuild(self, **kwargs):
        return rebuild_raw_resources(
            self.identity, self.manifest,
            bundle_root=self.bundles, candidate_root=self.candidates,
            formal_base=self.home, fetcher=self.fetch, extractor=self.extract,
            **kwargs)

    def test_all_current_and_new_raw_assets_are_included(self):
        report = self.rebuild()
        self.assertTrue(report['complete_raw_assets'])
        self.assertEqual(report['asset_total'], 2)
        self.assertEqual(report['asset_collected'], 2)
        self.assertEqual(report['newly_extracted'], 2)
        self.assertEqual(report['new_bundle_downloads'], 2)
        self.assertFalse(report['formal_approved'])
        self.assertFalse(report['assets_ready'])
        self.assertIn('release_pinned_catalog_manifest_missing',
                      report['formal_blockers'])
        self.assertIn('release_pinned_eve_indexes_missing',
                      report['formal_blockers'])
        archive = self.identity.private_catalog_dir(self.candidates) / 'verified_raw_inventory.zip'
        with ZipFile(archive) as z:
            names = z.namelist()
            self.assertIn('tables/datapackage_data_a.bundle/AlphaData_C.bytes', names)
            self.assertIn('tables/datapackage_data_b.bundle/TalkData_C.bytes', names)
            doc = json.loads(z.read('inventory.json'))
            self.assertEqual(set(doc['entries']) | {'inventory.json'}, set(names))
            self.assertEqual(doc['catalog_key'], self.identity.key)
        again = self.rebuild()
        self.assertEqual(again['new_bundle_downloads'], 0)
        self.assertEqual(again['existing_or_cached_reused'], 2)
        self.assertEqual(len(self.requests), 2)

    def test_bounded_download_then_resume_on_next_launcher_run(self):
        one = self.rebuild(max_downloads=1)
        self.assertEqual(one['asset_collected'], 1)
        self.assertEqual(len(one['missing_asset_paths']), 1)
        two = self.rebuild(max_downloads=1)
        self.assertEqual(two['asset_collected'], 2)
        self.assertTrue(two['complete_raw_assets'])
        self.assertEqual(len(self.requests), 2)
        self.assertFalse(two['can_send_packets'])

    def test_existing_pinned_table_is_reused_without_re_download(self):
        member = 'tables/datapackage_data_a.bundle/AlphaData_C.bytes'
        existing = b'existing SHA pinned and checked alpha'
        spec = {'bytes': len(existing),
                'sha256': hashlib.sha256(existing).hexdigest()}
        with patch('wlre.services.world.resource_rebuilder._checked_existing',
                   return_value=({member: existing},
                                 {'files': {member: spec}})) as checked:
            result = self.rebuild(max_downloads=0)
        checked.assert_called_once()
        self.assertEqual(result['asset_collected'], 1)
        self.assertEqual(result['existing_or_cached_reused'], 1)
        archive = self.identity.private_catalog_dir(self.candidates) / 'verified_raw_inventory.zip'
        with ZipFile(archive) as z:
            self.assertEqual(z.read(member), existing)
        self.assertEqual(self.requests, [])

    def test_existing_pinned_files_never_mix_into_next_revision(self):
        wrong = OfficialCatalogIdentity(
            '1.3.21','1.3.0',(
                PackageRevision('DataPackage',
                                '1276_2026_10_24_18_27_33_84',
                                'c'*64,'12345678'),
                self.identity.packages[1]))
        new = VerifiedManifest(
            ManifestSpec('1.3.21','DataPackage',
                         '1276_2026_10_24_18_27_33_84'),
            {**self.index, 'header': {
                **self.index['header'],
                'package_version':'1276_2026_10_24_18_27_33_84'}},
            '12345678', self.home/'new.bytes',False)
        with patch('wlre.services.world.resource_rebuilder._checked_existing') as checked:
            report = rebuild_raw_resources(
                wrong, new, bundle_root=self.bundles,
                candidate_root=self.candidates, formal_base=self.home,
                fetcher=self.fetch, extractor=self.extract,
                max_downloads=0)
        checked.assert_not_called()
        self.assertEqual(report['asset_collected'], 0)
        self.assertFalse(report['formal_approved'])

    def test_invalid_bundle_hash_does_not_get_reused(self):
        spec = spec_from_manifest(data_ver='1.3.21',
                                  package='DataPackage', index=self.index,
                                  name='datapackage_data_a.bundle')
        path = spec.cache_path(self.bundles)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'X'*len(self.payloads[spec.name]))
        report = self.rebuild(max_downloads=0)
        self.assertNotIn('Assets/ResourcesBuild/Data/AlphaData_C.bytes',
                         self.reads)
        self.assertIn('Assets/ResourcesBuild/Data/AlphaData_C.bytes',
                      report['missing_asset_paths'])
        self.assertFalse(report['complete_raw_assets'])

    def test_inventory_summary_is_display_only_and_version_bound(self):
        from wlre.services.world.resource_rebuilder import read_inventory_summary
        self.rebuild()
        summary = read_inventory_summary(
            self.identity.key, candidate_root=self.candidates)
        self.assertEqual(summary['asset_collected'], 2)
        self.assertEqual(summary['asset_total'], 2)
        self.assertEqual(summary['derived_index_candidates'], 0)
        self.assertIn('release_pinned_catalog_manifest_missing',
                      summary['formal_blockers'])
        self.assertIsNone(read_inventory_summary('0'*64, candidate_root=self.candidates))
        self.assertIsNone(read_inventory_summary('../wrong', candidate_root=self.candidates))

    def test_bundled_pinned_manifest_feeds_raw_resource_verification(self):
        member = 'tables/datapackage_data_a.bundle/AlphaData_C.bytes'
        expected = {'files': {
            member: {'kind': 'raw_table', 'table': 'AlphaData_C',
                     'bytes': 100, 'sha256': 'a' * 64},
            'indexes/npc_text_1275.json.gz': {
                'kind': 'read_only_index', 'bytes': 80, 'sha256': 'b' * 64},
        }}
        with patch('wlre.services.world.resource_rebuilder._checked_existing',
                   return_value=({}, None)), patch(
             'wlre.services.world.resource_rebuilder._exact_reviewed_manifest',
                   return_value=b'{"schema_version":1}'), patch(
             'wlre.services.world.game_data_1275._valid_manifest',
                   return_value=expected) as reviewed, patch(
             'wlre.services.world.resource_rebuilder._build_full_reviewed_if_pinned',
                   return_value='awaiting_pinned_catalog_members') as build:
            report = self.rebuild(max_downloads=0)
        reviewed.assert_called_once()
        self.assertEqual(build.call_args.args[3], expected['files'])
        self.assertNotIn('release_pinned_catalog_manifest_missing',
                         report['formal_blockers'])
        self.assertIn('release_pinned_raw_tables_missing',
                      report['formal_blockers'])
        self.assertIn('release_pinned_catalog_indexes_missing',
                      report['formal_blockers'])
        self.assertFalse(report['assets_ready'])
        self.assertFalse(report['can_send_packets'])

    def test_bundled_formal_manifest_is_independently_pinned_not_self_signed(self):
        from wlre.services.world.resource_rebuilder import _exact_reviewed_manifest
        pins = self.home / 'resource_bundle' / 'pins'
        pins.mkdir(parents=True)
        file = pins / '1275_DataCatalog.manifest.json'
        raw = b'{"schema_version":1,"official_resource_revision":1275}'
        file.write_bytes(raw)
        with patch('wlre.paths.RESOURCE_ROOT', pins.parent), patch(
                'wlre.services.world.game_data_1275.MANIFEST_SHA256',
                hashlib.sha256(raw).hexdigest()), patch(
                'wlre.services.world.game_data_1275._valid_manifest',
                return_value={}):
            self.assertEqual(_exact_reviewed_manifest(self.home), raw)
            file.write_bytes(raw + b' ')
            self.assertIsNone(_exact_reviewed_manifest(self.home))
            file.write_bytes(raw)
        with patch('wlre.paths.RESOURCE_ROOT', pins.parent), patch(
                'wlre.services.world.game_data_1275.MANIFEST_SHA256',
                hashlib.sha256(raw).hexdigest()), patch(
                'wlre.services.world.game_data_1275._valid_manifest',
                side_effect=ValueError('rejected schema')):
            self.assertIsNone(_exact_reviewed_manifest(self.home))

    def test_assembled_full_archives_revalidate_and_never_overwrite(self):
        from wlre.services.world import resource_rebuilder as mod
        from wlre.services.world.npc_1275_eve import FILES
        from wlre.services.world.runtime_1275 import DATA_FILE, EVE_FILE
        from unittest.mock import patch
        raw = b'pinned raw table'
        member = 'tables/datapackage_data_a.bundle/AlphaData_C.bytes'
        payloads = {member: raw, **{name: b'index fixture' for name in FILES}}
        pinned = {member: {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}
        with patch.object(mod, '_exact_reviewed_manifest',
                          return_value=b'fixed manifest'), patch(
            'wlre.services.world.game_data_1275.verify_archive') as verify, patch(
            'wlre.services.world.npc_1275_eve.read_verified_zip') as eve:
            result = mod._build_full_reviewed_if_pinned(
                self.identity,self.home,payloads,pinned)
            self.assertEqual(result, 'reviewed_archives_constructed')
            verify.assert_called_once()
            eve.assert_called_once()
        target = self.home / 'official_sync' / 'reviewed_full_1275'
        with ZipFile(target / DATA_FILE) as z:
            self.assertEqual(z.read(member), raw)
        with ZipFile(target / EVE_FILE) as z:
            self.assertEqual(set(z.namelist()), set(FILES) | {'README.txt'})
        # Pre-existing reviewed archives are never overwritten.
        again = mod._build_full_reviewed_if_pinned(
            self.identity,self.home,payloads,pinned)
        self.assertEqual(again, 'reviewed_archives_already_present')

    def test_failed_independent_pin_does_not_publish_formal_zip(self):
        from wlre.services.world import resource_rebuilder as mod
        from wlre.services.world.npc_1275_eve import FILES
        from wlre.services.world.runtime_1275 import DATA_FILE, EVE_FILE
        from unittest.mock import patch
        member = 'tables/datapackage_data_a.bundle/AlphaData_C.bytes'
        body = b'fake content'
        inputs = {member:body, **{name:b'fake' for name in FILES}}
        with patch.object(mod, '_exact_reviewed_manifest',
                          return_value=b'fixed manifest'), patch(
            'wlre.services.world.game_data_1275.verify_archive',
            side_effect=ValueError('Pinned SHA mismatch')):
            result = mod._build_full_reviewed_if_pinned(
                self.identity,self.home,inputs,{member:{}})
        self.assertEqual(result, 'reviewed_archive_verification_failed')
        target = self.home / 'official_sync' / 'reviewed_full_1275'
        self.assertFalse((target / DATA_FILE).exists())
        self.assertFalse((target / EVE_FILE).exists())

    def test_failed_bundle_download_attempts_once_per_bundle(self):
        self.index['assets'].append({
            'path':'Assets/ResourcesBuild/Data/ExtraData_C.bytes',
            'bundle_name':'datapackage_data_a.bundle'})
        def fail(spec, *, cache_root):
            self.requests.append(spec.name)
            raise OSError('offline')
        with patch('wlre.services.world.resource_rebuilder._checked_existing',
                   return_value=({}, None)):
            result = rebuild_raw_resources(
                self.identity,self.manifest,bundle_root=self.bundles,
                candidate_root=self.candidates,formal_base=self.home,
                fetcher=fail,extractor=self.extract)
        self.assertEqual(self.requests.count('datapackage_data_a.bundle'), 1)
        self.assertGreater(len(result['missing_asset_paths']), 0)


if __name__ == '__main__':
    unittest.main()
