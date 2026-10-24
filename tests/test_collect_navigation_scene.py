"""Read a real pinned MainPackage manifest, collect a pair, reject changed sources."""
from pathlib import Path
from zipfile import ZipFile
import json
import importlib.util
import tempfile
import unittest
from tools.resources.collect_navigation_scene import parse_manifest,collect,MANIFEST,SceneCollectionError
from tools.resources.extract_1275_recast_settings import load_scene_selection,scene_models

SOURCE=Path(__file__).resolve().parents[1]/'1275_差異'/'LaLa_1275_Scenes_差異Bundle_重建.zip'


@unittest.skipUnless(SOURCE.is_file(),'Private/source scene archive not supplied')
class CurrentSceneCollection(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.yoo=self.root/'game'/'yoo'
        with ZipFile(SOURCE) as z:
            member='source/MainPackage/ManifestFiles/'+MANIFEST
            self.raw=z.read(member);self.rows=parse_manifest(self.raw)
            path=self.yoo/'MainPackage'/'ManifestFiles'/MANIFEST;path.parent.mkdir(parents=True);path.write_bytes(self.raw)
            for name in ('mainpackage_scene_12910.bundle','mainpackage_scene_12910_dependency.bundle'):
                row=self.rows[name];relative=f"MainPackage/BundleFiles/{row['file_hash'][:2]}/{row['file_hash']}/__data"
                path=self.yoo/relative;path.parent.mkdir(parents=True);path.write_bytes(z.read('source/'+relative))
    def test_actual_manifest_finds_current_12170_pair_without_old_diff_list(self):
        self.assertEqual(len(self.rows),1732)
        self.assertEqual(self.rows['mainpackage_scene_12170.bundle']['size'],49532)
        self.assertEqual(self.rows['mainpackage_scene_12170_dependency.bundle']['size'],818949)
    def test_collection_is_self_contained_and_hash_checked(self):
        output=self.root/'model.zip';result=collect(self.yoo,12910,output)
        self.assertEqual(result['bundles'],2)
        selection=load_scene_selection(output)
        self.assertEqual(scene_models(selection),{12910})
        self.assertEqual(len(selection['bundles']),2)
        with self.assertRaises(FileExistsError):collect(self.yoo,12910,output)
    def test_wrong_source_and_game_folder_outputs_are_rejected(self):
        path=next(self.yoo.glob('MainPackage/BundleFiles/*/*/__data'));path.write_bytes(b'changed')
        output=self.root/'bad.zip'
        with self.assertRaises(SceneCollectionError):collect(self.yoo,12910,output)
        self.assertFalse(output.exists())
        with self.assertRaises(SceneCollectionError):collect(self.yoo,12910,self.yoo/'result.zip')
    def test_modified_manifest_is_rejected(self):
        raw=bytearray(self.raw);raw[-1]^=1
        with self.assertRaises(SceneCollectionError):parse_manifest(raw)

    @unittest.skipUnless(importlib.util.find_spec('lz4'),'Requires optional lz4 for UnityFS integration')
    def test_self_contained_pair_reaches_graph_and_collision_readers(self):
        from tools.resources.extract_1275_recast_settings import extract
        from tools.resources.audit_1275_scene_collision import inspect
        output=self.root/'one-scene.zip';collect(self.yoo,12910,output)
        self.assertEqual(inspect(output)['scene_count'],1)
        graphs=extract(output)
        self.assertEqual(graphs['scene_count'],1)
        self.assertEqual(graphs['scenes'][0]['model_id'],12910)
        from tools.resources.audit_1275_scene_collision import main as audit_main
        from tools.resources.extract_1275_recast_settings import main as extract_main
        import contextlib,io
        with contextlib.redirect_stdout(io.StringIO()):
            audit_main(['--scenes-zip',str(output),'--output',str(self.root/'audit.json')])
            extract_main(['--scenes-zip',str(output),'--output',str(self.root/'graphs.json')])
        self.assertEqual(json.loads((self.root/'graphs.json').read_text())['scene_count'],1)
