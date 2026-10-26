"""Future-week revision identity uses both official full versions, not 1275."""

import tempfile
import unittest
import zlib

from test_official_manifest_integration import synthetic_manifest
from tools.resources.lala_manifest_full_index import parse_manifest
from wlre.services.official_manifest_sync import ManifestSpec, VerifiedManifest
from wlre.services.world.catalog_identity import (
    CatalogIdentityError, REQUIRED_FEATURES, identity_from_verified_manifests,
)


DATA = '1275_2026_10_21_18_27_33_84'
MAIN = '1275_2026_10_21_18_29_38_49'


def sources(root, *, data_ver='1.3.21', exe_ver='1.3.21',
            data_rev=DATA, main_rev=MAIN):
    snapshot = {
        'schema_version': 1, 'origin': 'official_pc_version_endpoint',
        'data_ver': data_ver, 'exe_version': exe_ver,
        'packages': {'DataPackage': data_rev, 'MainPackage': main_rev},
        'checked_at_utc': '2026-10-24T00:00:00+00:00', 'assets_ready': False,
    }
    manifests = {}
    for package, revision in snapshot['packages'].items():
        spec = ManifestSpec(data_ver, package, revision)
        body = synthetic_manifest(package_version=revision, package_name=package)
        crc = zlib.crc32(body).to_bytes(4, 'little').hex()
        path = spec.cache_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        manifests[package] = VerifiedManifest(spec, parse_manifest(body), crc, path, True)
    return snapshot, manifests


class CatalogRevisionTests(unittest.TestCase):
    def test_two_packages_and_private_identity_for_1275(self):
        with tempfile.TemporaryDirectory() as root:
            snapshot, manifests = sources(root)
            identity = identity_from_verified_manifests(snapshot, manifests)
            self.assertEqual(identity.data_ver, '1.3.21')
            self.assertEqual(len(identity.packages), 2)
            self.assertEqual(len(identity.key), 64)
            self.assertEqual(identity.private_catalog_dir(root).name, identity.key)
            self.assertEqual(set(REQUIRED_FEATURES), {'npc', 'shops', 'crafting', 'scenes'})
            self.assertNotIn('assets_ready', identity.as_dict())

    def test_next_week_1276_not_pinned_to_1275(self):
        with tempfile.TemporaryDirectory() as root:
            original = identity_from_verified_manifests(*sources(root))
            next_week = identity_from_verified_manifests(*sources(
                root, data_ver='1.3.22', exe_ver='1.3.22',
                data_rev='1276_2026_10_29_08_00_00_01',
                main_rev='1276_2026_10_29_08_05_00_01'))
            self.assertNotEqual(original.key, next_week.key)
            self.assertEqual(next_week.data_ver, '1.3.22')

    def test_same_numeric_revision_republished_manifest_gets_new_identity(self):
        with tempfile.TemporaryDirectory() as root:
            initial = identity_from_verified_manifests(*sources(root))
            republished = identity_from_verified_manifests(*sources(
                root, data_rev='1275_2026_10_25_18_27_33_84'))
            self.assertNotEqual(initial.key, republished.key)

    def test_independent_main_package_revision_changes_identity(self):
        with tempfile.TemporaryDirectory() as root:
            initial = identity_from_verified_manifests(*sources(root))
            updated = identity_from_verified_manifests(*sources(
                root, main_rev='1275_2026_10_26_18_29_38_49'))
            self.assertNotEqual(initial.key, updated.key)

    def test_corrupted_manifest_or_missing_package_does_not_activate(self):
        with tempfile.TemporaryDirectory() as root:
            snapshot, manifests = sources(root)
            with self.assertRaises(CatalogIdentityError):
                identity_from_verified_manifests(snapshot, {'DataPackage': manifests['DataPackage']})
            bad_path = manifests['MainPackage'].cache_path
            bad_path.write_bytes(b'corrupt')
            with self.assertRaisesRegex(CatalogIdentityError, 'CRC'):
                identity_from_verified_manifests(snapshot, manifests)


if __name__ == '__main__':
    unittest.main()
