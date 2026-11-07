import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from wlre.services.world import navigation_sync as sync
from wlre.services.world.navigation_database import REVIEWED_MODELS
from wlre.services.world.astar_cache import REVIEWED_CACHES


class NavigationRegistryTests(unittest.TestCase):
    def test_model_registry_and_decoder_are_consistent(self):
        self.assertEqual(set(REVIEWED_MODELS.values()),set(REVIEWED_CACHES))
        for digest in REVIEWED_MODELS.values():
            self.assertEqual(len(digest),64)
            int(digest,16)

    def test_degenerate_models_are_not_promoted(self):
        for model in (12366,12507,12512,12662):
            self.assertNotIn(model,REVIEWED_MODELS)

    def test_shared_cache_requires_exact_cab_path_and_reviewed_name(self):
        ref={'m_FileID':1,'m_PathID':7}
        source=SimpleNamespace(type=SimpleNamespace(name='MonoBehaviour'),
            assets_file=SimpleNamespace(externals=[SimpleNamespace(path='archive:/CAB-test/CAB-test')]),
            read_typetree=lambda:{'data':{'file_cachedStartup':ref,'cacheStartup':1}})
        tree={'m_Name':'15011','m_Script':b'candidate'}
        target=SimpleNamespace(type=SimpleNamespace(name='TextAsset'),path_id=7,
            assets_file=SimpleNamespace(name='CAB-test'),read_typetree=lambda:tree)
        def loader(path):return SimpleNamespace(objects=[source] if path=='scene' else [target])
        with patch.dict('sys.modules',{'UnityPy':SimpleNamespace(load=loader)}):
            raw,pointer=sync.extract_cache(['scene','dependency'],15012)
            self.assertEqual(raw,b'candidate')
            self.assertEqual(pointer['textasset_name'],'15011')
            with self.assertRaisesRegex(ValueError,'model mismatch'):
                sync.extract_cache(['scene','dependency'],15013)
            target.path_id=8
            with self.assertRaisesRegex(ValueError,'CAB/path ID'):
                sync.extract_cache(['scene','dependency'],15012)
            target.path_id=7;target.assets_file.name='CAB-other'
            with self.assertRaisesRegex(ValueError,'CAB/path ID'):
                sync.extract_cache(['scene','dependency'],15012)

    def test_only_explicit_shared_dependency_is_used(self):
        self.assertEqual(sync.REVIEWED_DEPENDENCY_MODELS,{15012:15011})
        self.assertEqual(sync.REVIEWED_CACHE_NAMES,{10082:'11082',15012:'15011'})
        self.assertEqual(sync.MAX_FILES,2)
        self.assertEqual(sync.MAX_BYTES,32*1024*1024)
