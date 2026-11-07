from types import SimpleNamespace
from unittest.mock import patch
import unittest
from wlre.services.world.portrait_assets import source_specs, _pointer, _wanted, VERSION


class PortraitAssetTests(unittest.TestCase):
    def test_unknown_source_version_fails_closed(self):
        manifest = SimpleNamespace(spec=SimpleNamespace(data_ver='1.3.24', package='MainPackage', package_version=VERSION))
        with self.assertRaises(ValueError):
            source_specs(manifest)

    def test_incomplete_or_ambiguous_catalog_fails(self):
        manifest = SimpleNamespace(index={'assets': []})
        with self.assertRaises(ValueError):
            _wanted(manifest)
        path = 'Assets/ResourcesBuild/Other/Avatar2DMaterial/0001/PhotoAvatar_0001.mat'
        row = dict(path=path, bundle_name='mainpackage_material.bundle')
        manifest.index['assets'] = [row, row]
        with self.assertRaisesRegex(ValueError, '重複'):
            _wanted(manifest)

    def test_pptr_is_scoped_by_serialized_file(self):
        obj = object()
        owner = SimpleNamespace(assets_file=SimpleNamespace(name='a', externals=[SimpleNamespace(name='b')]))
        objects = {('b', 7): obj}
        self.assertIs(_pointer(owner, {'m_FileID': 1, 'm_PathID': 7}, objects), obj)
        with self.assertRaises(ValueError):
            _pointer(owner, {'m_FileID': 0, 'm_PathID': 7}, objects)
        with self.assertRaises(ValueError):
            _pointer(owner, {'m_FileID': 2, 'm_PathID': 7}, objects)
        self.assertIsNone(_pointer(owner, {'m_FileID': 0, 'm_PathID': 0}, objects, allow_null=True))
        with self.assertRaises(ValueError):
            _pointer(owner, {'m_FileID': 1, 'm_PathID': 0}, objects, allow_null=True)


if __name__ == '__main__':
    unittest.main()
