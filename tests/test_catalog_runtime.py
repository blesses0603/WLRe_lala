"""Official-only Catalog Runtime regression tests; no candidate workflow."""
import hashlib
import json
import unittest
from wlre.services.world.catalog_adapters import CatalogAdapterError, SourceContract
from wlre.services.world.catalog_runtime import (
    official_package_versions, official_catalog_key, select_catalog_runtime,
    validate_official_catalog,
)


class CatalogRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.remote = {
            'resource_path': '1.3.21', 'official_exe_version': '1.3.0',
            'newer_official_client': False,
            'packages': {
                'DataPackage': {'remote': '1286_2026_10_29_13_42_37_94'},
                'MainPackage': {'remote': '1284_2026_10_28_12_00_00_00'},
            },
        }

    def test_distinct_package_revisions_are_supported(self):
        self.assertEqual(len(official_package_versions(self.remote)), 2)
        decision = select_catalog_runtime(self.remote)
        self.assertEqual(decision.status, 'verification_required')
        self.assertFalse(decision.assets_ready)
        self.assertFalse(decision.can_send_packets)

    def test_identity_key_changes_on_either_package(self):
        old = official_catalog_key(self.remote)
        self.remote['packages']['MainPackage']['remote'] = '1290'
        self.assertNotEqual(old, official_catalog_key(self.remote))

    def test_missing_extra_and_invalid_package_fail_closed(self):
        for name in ('DataPackage', 'MainPackage'):
            with self.subTest(name=name):
                remote = dict(self.remote, packages=dict(self.remote['packages']))
                del remote['packages'][name]
                self.assertEqual(select_catalog_runtime(remote).status, 'blocked')
        remote = dict(self.remote, packages=dict(self.remote['packages'], Other={'remote': '1'}))
        self.assertEqual(select_catalog_runtime(remote).status, 'blocked')
        self.remote['packages']['MainPackage']['remote'] = ''
        self.assertEqual(select_catalog_runtime(self.remote).status, 'blocked')

    def test_unverified_client_and_pair_mismatch_block(self):
        self.remote['newer_official_client'] = True
        self.assertEqual(select_catalog_runtime(self.remote).status, 'verification_required')
        self.remote['newer_official_client'] = None
        self.assertEqual(select_catalog_runtime(self.remote).status, 'blocked')
        self.remote['newer_official_client'] = False
        self.assertEqual(select_catalog_runtime(self.remote, package_versions={}).status, 'blocked')

    def test_no_partial_or_untrusted_sources(self):
        with self.assertRaises(CatalogAdapterError):
            validate_official_catalog(self.remote, contracts={}, source_payloads={})
        with self.assertRaises(CatalogAdapterError):
            validate_official_catalog(self.remote, contracts={'npc': object()}, source_payloads={})

    def test_contract_package_pair_must_match(self):
        contract = SourceContract('npc', 'npc.json', 'eve-npc-json-v1', 'a'*64,
                                  'MainPackage', 'not-official')
        contracts = {name: contract for name in ('npc', 'shops', 'crafting', 'scenes')}
        with self.assertRaises(CatalogAdapterError):
            validate_official_catalog(self.remote, contracts=contracts, source_payloads={})


if __name__ == '__main__':
    unittest.main()
