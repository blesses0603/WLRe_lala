"""五個模組資料來源策略回歸測試；不連接官方伺服器。"""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from wlre.services.world.catalog_source_policy import (
    FEATURES, source_for, official_runtime,
)


class CatalogSourcePolicyTests(unittest.TestCase):
    def test_five_features_share_one_verified_1275_source(self):
        self.assertEqual(len(FEATURES), 5)
        for feature in FEATURES:
            with self.subTest(feature=feature), patch(
                'wlre.services.world.runtime_1275.baseline_revision',
                return_value='1275'
            ):
                result = source_for(feature)
                self.assertEqual(result.kind, 'verified_1275_runtime')
                self.assertTrue(result.gameplay_allowed)

    def test_legacy_never_grants_gameplay_permission(self):
        for feature in FEATURES:
            result = source_for(feature, revision='1262')
            self.assertFalse(result.authoritative)
            self.assertFalse(result.gameplay_allowed)

    def test_unrecognized_revision_and_feature_fail_closed(self):
        with self.assertRaises(ValueError):
            source_for('items', revision='9999')
        with self.assertRaises(ValueError):
            source_for('social', revision='1275')

    def test_runtime_requires_matching_revision(self):
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
            'wlre.services.world.runtime_1275.active_runtime',
            return_value=SimpleNamespace(revision=1262)
        ):
            with self.assertRaises(ValueError):
                official_runtime('items')

    def test_runtime_is_shared_across_all_five(self):
        runtime = SimpleNamespace(revision=1275)
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
            'wlre.services.world.runtime_1275.active_runtime',
            return_value=runtime
        ):
            for feature in FEATURES:
                self.assertIs(official_runtime(feature), runtime)


if __name__ == '__main__':
    unittest.main()
