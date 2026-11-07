"""No shipped portal snapshot is needed for current or cold-start reads."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from wlre.services.world.portals import Portals


class PortalSourceRetirementTests(unittest.TestCase):
    def test_cold_start_never_reads_existing_legacy_database(self):
        with patch('wlre.services.world.runtime_1275.baseline_revision', return_value='1275'), patch('wlre.services.world.catalog_source_policy.official_runtime', side_effect=ValueError('unavailable')), patch('wlre.storage.bundled_database.load_bundled_json', side_effect=AssertionError('legacy read')):
            portals = Portals()
        self.assertFalse(portals.data['source_ready'])
        self.assertEqual(portals.for_scene(10000), [])
        self.assertEqual(portals.data['portal_metadata_status'], 'core_runtime_unavailable')

    def test_explicit_archive_remains_available_without_shipped_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'archive.json'
            path.write_text(json.dumps({'portals': {'10000': [{'id': 'historical'}]}, 'audit': []}))
            portals = Portals(path)
        self.assertEqual(portals.for_scene(10000), [{'id': 'historical'}])

    def test_empty_explicit_path_cannot_select_bundled_fallback(self):
        with patch('wlre.storage.bundled_database.load_bundled_json', side_effect=AssertionError('legacy read')):
            with self.assertRaises(OSError):
                Portals('')
