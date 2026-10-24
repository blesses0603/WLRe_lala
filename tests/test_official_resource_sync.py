"""Offline-only safety and state tests; no live CDN calls or game assets."""

import json
from pathlib import Path
import tempfile
import unittest

from wlre.services import official_version
from wlre.services.official_resource_sync import (
    OfficialSyncError, compare_snapshot, observe_official_versions,
    read_snapshot, save_snapshot, validate_snapshot,
)


RESOURCE_MAP = (b'[\r\n'
                b'{"ExeVer":"1.1.3","DataVer":"1.3.21"},\r\n'
                b'{"ExeVer":"1.1.4","DataVer":"1.3.21"},\r\n'
                b'{"ExeVer":"1.2.0","DataVer":"1.3.21"},\r\n'
                b'{"ExeVer":"1.3.0","DataVer":"1.3.21"},\r\n]')
DATA = b'1275_2026_10_21_18_27_33_84'
MAIN = b'1275_2026_10_21_18_29_38_49'


def fake_fetcher():
    urls = official_version.official_package_urls('1.3.21')
    responses = {official_version.RESOURCE_MAP_URL: RESOURCE_MAP,
                 urls['DataPackage']: DATA, urls['MainPackage']: MAIN}
    seen = []

    def fetch(url):
        seen.append(url)
        return responses[url]

    return fetch, seen, urls


class OfficialResourceSyncTests(unittest.TestCase):
    def test_three_step_bootstrap_no_game_install(self):
        fetch, seen, urls = fake_fetcher()
        value = observe_official_versions(fetcher=fetch, checked_at='2026-10-24T00:00:00+00:00')
        self.assertEqual(seen, [official_version.RESOURCE_MAP_URL,
                                urls['DataPackage'], urls['MainPackage']])
        self.assertEqual(value['data_ver'], '1.3.21')
        self.assertEqual(value['packages']['MainPackage'], MAIN.decode())
        self.assertFalse(value['assets_ready'])
        self.assertFalse(compare_snapshot(value)['can_start_asset_dependent_features'])

    def test_incremental_versions_only(self):
        fetch, _, _ = fake_fetcher()
        first = observe_official_versions(fetcher=fetch)
        later = dict(first, packages=dict(first['packages']))
        self.assertEqual(compare_snapshot(later, first)['package_changes']['MainPackage'], 'unchanged')
        later['packages']['MainPackage'] = '1276_2026_10_29_18_29_38_49'
        result = compare_snapshot(later, first)
        self.assertEqual(result['package_changes']['MainPackage'], 'changed')
        self.assertEqual(result['package_changes']['DataPackage'], 'unchanged')

    def test_atomic_cache_and_corruption_rejection(self):
        fetch, _, _ = fake_fetcher()
        value = observe_official_versions(fetcher=fetch)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'official_sync' / 'pc_versions.json'
            self.assertIsNone(read_snapshot(target))
            self.assertEqual(save_snapshot(value, target), target)
            self.assertEqual(read_snapshot(target), value)
            target.write_bytes(b'{not json}')
            with self.assertRaises(OfficialSyncError):
                read_snapshot(target)
            target.write_bytes(b'x' * 5000)
            with self.assertRaises(OfficialSyncError):
                read_snapshot(target)

    def test_invalid_version_and_no_silent_download(self):
        fetch, _, urls = fake_fetcher()
        def bad(url):
            if url == urls['MainPackage']:
                return b'invalid-version'
            return fetch(url)
        with self.assertRaises(OfficialSyncError):
            observe_official_versions(fetcher=bad)
        value = observe_official_versions(fetcher=fetch)
        altered = dict(value, assets_ready=True)
        with self.assertRaises(OfficialSyncError):
            validate_snapshot(altered)

    def test_cache_is_metadata_only(self):
        fetch, _, _ = fake_fetcher()
        value = observe_official_versions(fetcher=fetch)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'pc_versions.json'
            save_snapshot(value, target)
            doc = json.loads(target.read_text(encoding='utf-8'))
            self.assertNotIn('bundle_files', doc)
            self.assertNotIn('asset_data', doc)
            self.assertFalse(doc['assets_ready'])


if __name__ == '__main__':
    unittest.main()
