from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class ConfigurationWithoutSeedTests(unittest.TestCase):
    def test_release_policy_and_profile_need_no_resource_files(self):
        from wlre.services.resource_compatibility import load_supported_resources
        from wlre.storage.defaults import load_default_profile
        with tempfile.TemporaryDirectory() as directory, \
                patch('wlre.storage.full_resource_seed.read_config', side_effect=AssertionError('seed accessed')), \
                patch('wlre.services.resource_compatibility.RESOURCE_ROOT', Path(directory)), \
                patch('wlre.storage.defaults.RESOURCE_ROOT', Path(directory)):
            self.assertEqual(load_supported_resources()['schema_version'], 1)
            first = load_default_profile(); first['game_endpoint']['host'] = 'changed'
            self.assertNotEqual(load_default_profile()['game_endpoint']['host'], 'changed')

    def test_policy_return_is_independent_and_downloads_cannot_replace_it(self):
        from wlre.services.resource_compatibility import load_supported_resources
        first = load_supported_resources()
        first['packages']['DataPackage']['revision'] = '9999'
        self.assertNotEqual(load_supported_resources()['packages']['DataPackage']['revision'], '9999')

    def test_migrated_values_preserve_reviewed_policy_and_protocol(self):
        import hashlib, json
        from wlre.configuration import DEFAULT_PROFILE, PROTOCOL_ENUMS, SUPPORTED_RESOURCES
        expected = {'default_profile.json': '7adf0812d3165c334c52ba970994056ae4460ced5bb76ee0986e83e44d998c03', 'enums.json': '0ee17a685605b2eb98bb527c997417b1b7354281e4d084c332d3f3d21f5626bb', 'lala_supported_resources.json': 'c6c9b9c55b61c949448be09be7e770f7b8b2b8430f3ffe0bc96a32766734e86a'}
        for name, value in [('default_profile.json', DEFAULT_PROFILE), ('enums.json', PROTOCOL_ENUMS),
                            ('lala_supported_resources.json', SUPPORTED_RESOURCES)]:
            canonical=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected[name])
