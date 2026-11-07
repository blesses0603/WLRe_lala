import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from tools.audit_official_navigation_coverage import inventory,audit
from wlre.services.world.navigation_sync import MAX_BYTES


def index(model=10001,size=100):
    root=f'mainpackage_scene_{model}.bundle';dep=f'mainpackage_scene_{model}_dependency.bundle'
    return dict(assets=[dict(address=f'M{model}',path=f'Assets/M{model}.unity',bundle_name=root)],bundles=[dict(name=root,dependencies=[dep],file_size=size),dict(name=dep,file_size=size)])


class CoverageTests(unittest.TestCase):
    def test_inventory_is_candidates_not_authority(self):
        result=inventory({10001:dict(model_id=10001),61501:dict(model_id=10001),10000:dict(model_id=10000),63501:dict(model_id=10001)},index())
        self.assertEqual(result['stage_count'],2);self.assertEqual(result['model_count'],1)
        self.assertEqual(result['excluded_house_stages'],[10000,63501])
        self.assertFalse(result['can_send_packets']);self.assertFalse(result['models'][0]['can_send_packets'])
        self.assertEqual(result['models'][0]['status'],'within_download_budget')

    def test_missing_ambiguous_dependency_and_budget(self):
        stages={10001:dict(model_id=10001)}
        for mutate,expected in ((lambda d:d['assets'].clear(),'missing_or_ambiguous_scene_asset'),(lambda d:d['assets'].append(d['assets'][0]),'missing_or_ambiguous_scene_asset'),(lambda d:d['bundles'][0]['dependencies'].clear(),'candidate_dependency_not_declared'),(lambda d:d['bundles'].pop(),'missing_or_ambiguous_bundle')):
            d=index();mutate(d);self.assertEqual(inventory(stages,d)['models'][0]['status'],expected)
        self.assertEqual(inventory(stages,index(size=MAX_BYTES))['models'][0]['status'],'exceeds_download_budget')

    def test_exact_manifest_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'manifest';path.write_bytes(b'verified')
            revision=NS(name='MainPackage',full_version='v',manifest_sha256=hashlib.sha256(b'verified').hexdigest())
            runtime=NS(catalog_identity=NS(key='a'*64,data_ver='1',packages=[revision]),stages={10001:dict(model_id=10001)})
            manifest=NS(spec=NS(data_ver='1',package='MainPackage',package_version='v'),cache_path=path,index=index())
            self.assertEqual(audit(runtime,manifest)['catalog_key'],'a'*64)
            manifest.spec.package_version='stale'
            with self.assertRaises(ValueError):audit(runtime,manifest)
            manifest.spec.package_version='v';path.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):audit(runtime,manifest)
