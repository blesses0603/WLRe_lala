"""No-manual-ZIP official DataPackage receiving and bounded continuation tests."""
import unittest
from unittest.mock import patch

from wlre.services.world.auto_catalog import _rebuild_known_resources


class AutomaticRawReceiverTests(unittest.TestCase):
    def test_batches_continue_without_restart_and_preserve_safety(self):
        calls = []
        stages = []
        reports = []
        for count in (1, 2, 3):
            reports.append({
                'asset_total': 3, 'asset_collected': count,
                'new_bundle_downloads': 1,
                'new_bundle_download_bytes': 2 * 1024 * 1024,
                'complete_raw_assets': count == 3,
                'formal_approved': False, 'assets_ready': False,
                'can_send_packets': False,
            })

        def rebuild(*args, **kwargs):
            calls.append((args, kwargs))
            return reports[len(calls) - 1]

        with patch('wlre.services.world.resource_rebuilder.rebuild_raw_resources',
                   side_effect=rebuild):
            report = _rebuild_known_resources(
                {'download_bytes': 4 * 1024 * 1024,
                 'downloads_required': 2},
                identity=object(), manifests={'DataPackage': object()},
                bundle_root=None, candidate_root=None,
                max_download_bytes=16 * 1024 * 1024, max_downloads=12,
                opener=None, progress=lambda phase, info: stages.append(phase))
        self.assertEqual(len(calls), 3)
        self.assertEqual(report['new_bundle_downloads'], 3)
        self.assertEqual(report['status'], 'complete_raw_only')
        self.assertFalse(report['assets_ready'])
        self.assertFalse(report['can_send_packets'])
        self.assertEqual(calls[0][1]['max_download_bytes'], 12 * 1024 * 1024)
        self.assertEqual(calls[1][1]['max_download_bytes'], 10 * 1024 * 1024)
        self.assertEqual(stages[0], 'raw_rebuild')
        self.assertEqual(stages[-1], 'raw_rebuild_ready')

    def test_fatal_decoder_does_not_disable_other_downloads(self):
        with patch('wlre.services.world.resource_rebuilder.rebuild_raw_resources',
                   side_effect=ValueError('unrecognized TextAsset')), \
             patch('wlre.services.official_bundle_download.fetch_bundle'):
            result = _rebuild_known_resources(
                {'download_bytes': 0, 'downloads_required': 0},
                identity=object(), manifests={'DataPackage': object()},
                bundle_root=None, candidate_root=None,
                max_download_bytes=16 * 1024 * 1024,
                max_downloads=4, opener=None, progress=None)
        self.assertEqual(result['status'], 'pending_error')
        self.assertFalse(result['assets_ready'])
        self.assertFalse(result['can_send_packets'])

    def test_stalled_missing_bundle_stops_instead_of_looping(self):
        calls = []
        def stalled(*args, **kwargs):
            calls.append(kwargs)
            return {'asset_total': 190, 'asset_collected': 50,
                    'new_bundle_downloads': 0,
                    'new_bundle_download_bytes': 0,
                    'complete_raw_assets': False,
                    'formal_approved': False, 'assets_ready': False,
                    'can_send_packets': False}
        with patch('wlre.services.world.resource_rebuilder.rebuild_raw_resources',
                   side_effect=stalled):
            report = _rebuild_known_resources(
                {'download_bytes': 0, 'downloads_required': 0},
                identity=object(), manifests={'DataPackage': object()},
                bundle_root=None, candidate_root=None,
                max_download_bytes=64 * 1024 * 1024,
                max_downloads=32, opener=None, progress=None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(report['status'], 'partial_raw')
        self.assertEqual(report['asset_collected'], 50)


if __name__ == '__main__':
    unittest.main()
