"""Historical bundled SQLite must not replace an unavailable official runtime."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from wlre.services.expedition import data
from wlre.services.world.runtime_1275 import Runtime1275Unavailable

class OfficialExpeditionSourceTests(unittest.TestCase):
    def test_public_entry_returns_copy_of_verified_runtime(self):
        fixture={'tasks':{'1':{'name':'fixture'}},'levels':{'1':{'teams':1}},'npcs':{}}
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=SimpleNamespace(expedition=fixture)):
            saved=data.load_catalog()
            saved['tasks']['1']['name']='changed'
            self.assertEqual(data.load_active_catalog()['tasks']['1']['name'],'fixture')

    def test_cold_or_failed_runtime_never_uses_old_seed(self):
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=None), patch('wlre.storage.bundled_database.load_bundled_json',side_effect=AssertionError('legacy seed read')):
            for attempted in (False,True):
                with self.subTest(attempted=attempted), patch('wlre.services.world.dynamic_bundle_runtime.dynamic_attempted',return_value=attempted), patch('wlre.services.world.runtime_1275.baseline_revision',return_value='1262'):
                    with self.assertRaises(Runtime1275Unavailable):data.load_catalog()
