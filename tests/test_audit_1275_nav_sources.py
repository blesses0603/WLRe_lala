"""Source-pinned 1262/1275 global Unity resource parity: not A* proof."""
import hashlib
import json
import tempfile
import unittest
import warnings
from pathlib import Path
from zipfile import ZipFile

from tools.resources.audit_1275_nav_sources import (
    OFFICIAL_MANIFEST_SHA256, NavSourceAuditError, audit,
)


class NavSourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / 'old.zip'
        self.new = self.root / 'new.zip'

    def write_both(self, *, old_data=b'a', new_data=b'a', signed=True,
                   duplicate=False):
        files_old = {'resources.assets': old_data,
                     'resources.resource': b'FSB5' + b'\x01' * 20}
        files_new = {'resources.assets': new_data,
                     'resources.resource': b'FSB5' + b'\x01' * 20}
        with ZipFile(self.old, 'w') as z:
            for key, value in files_old.items():
                z.writestr(key, value)
        manifest = {
            'revision': 1275,
            'yoo_manifests': {k: {'sha256': v} for k, v in
                               OFFICIAL_MANIFEST_SHA256.items()},
            'unity_files': {name: {
                'size': len(value), 'sha256': hashlib.sha256(value).hexdigest()
            } for name, value in files_new.items()},
        }
        if not signed:
            manifest['unity_files']['resources.assets']['sha256'] = '0' * 64
        with ZipFile(self.new, 'w') as z:
            z.writestr('source_fingerprints.json', json.dumps(manifest))
            for key, value in files_new.items():
                z.writestr('source/' + key, value)
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    z.writestr('source/resources.assets', new_data)

    def test_equal_bytes_do_not_enable_navigation(self):
        self.write_both()
        result = audit(self.old, self.new)
        self.assertTrue(result['global_resource_files_identical'])
        self.assertTrue(result['resources_resource_is_fsb5'])
        self.assertFalse(result['astar_graphs_extracted'])
        self.assertFalse(result['navmesh_verified'])
        self.assertFalse(result['auto_movement_authorized'])

    def test_different_assets_are_detected_without_claiming_movement(self):
        self.write_both(new_data=b'b')
        result = audit(self.old, self.new)
        self.assertFalse(result['global_resource_files_identical'])
        self.assertFalse(result['auto_movement_authorized'])

    def test_tampered_pin_or_duplicate_member_is_rejected(self):
        self.write_both(signed=False)
        with self.assertRaises(NavSourceAuditError):
            audit(self.old, self.new)
        self.write_both(duplicate=True)
        with self.assertRaises(NavSourceAuditError):
            audit(self.old, self.new)


if __name__ == '__main__':
    unittest.main()
