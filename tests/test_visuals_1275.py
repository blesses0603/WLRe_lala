"""1275 private image cache provenance and no-1262 graphical fallback."""
import io
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile
from PIL import Image

from wlre.services.world.visuals_1275 import (
    RESOURCE_SOURCES, VisualResourceError, verify_private_cache)
from wlre.services.world.smallmaps import SmallMaps


def png():
    image=Image.new('RGBA',(4,4),(90,30,130,255))
    buffer=io.BytesIO();image.save(buffer,'PNG');return buffer.getvalue()


def write_fixture(path, kind, names):
    blob=png()
    source, digest, filename, _=RESOURCE_SOURCES[kind]
    with ZipFile(path,'x') as archive:
        archive.writestr('manifest.json',json.dumps({
            'schema_version':1,'resource_revision':1275,'kind':kind,
            'source_bundle':source,'source_bundle_sha256':digest,
            'image_count':len(names),'images':{
                name:hashlib.sha256(blob).hexdigest() for name in names}}))
        if kind=='smallmaps':
            archive.writestr('image_index.json',json.dumps([
                {'name':name[:-4],'entry':name} for name in names]))
        for name in names:archive.writestr(name,blob)
    return blob


class Visual1275Tests(unittest.TestCase):
    def test_pinned_cache_rejects_tampered_1275_icon_pixels(self):
        import wlre.services.world.visuals_1275 as visual
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'item_icons_1275.zip'
            names=['s4253.png','s9937.png']
            with patch.dict(visual.RESOURCE_SOURCES, {
                'icons':(*RESOURCE_SOURCES['icons'][:3], 2)}):
                write_fixture(path,'icons',names)
                with self.assertRaises(VisualResourceError):
                    verify_private_cache(path,'icons') # Must contain all 15 new sprites.

    def test_smallmap_zip_uses_official_model_names_only(self):
        import wlre.services.world.visuals_1275 as visual
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'smallmaps_1275.zip'
            write_fixture(path,'smallmaps',('SmallMap2D_12910.png',
                                            'SmallMap2D_10001.png'))
            with patch.dict(visual.RESOURCE_SOURCES, {
                'smallmaps':(*RESOURCE_SOURCES['smallmaps'][:3], 2)}), \
                 patch('wlre.services.world.runtime_1275.baseline_revision',
                       return_value='1275'), \
                 patch('wlre.services.world.runtime_1275.resource_dir',
                       return_value=Path(d)), \
                 patch('wlre.services.world.runtime_1275.active_runtime',
                       return_value=SimpleNamespace(stages={
                           10000:{'model_id':12910},10001:{'model_id':13216}})):
                self.assertEqual(verify_private_cache(path,'smallmaps')['image_count'],2)
                maps=SmallMaps()
                self.assertTrue(maps.has_image(10000))
                self.assertFalse(maps.has_image(10001))
                self.assertEqual(maps.image(12910).size,(4,4))
                from wlre.services.world.navigation import NavigationError
                with self.assertRaises(NavigationError):
                    maps.for_model(12910)

    def test_no_1275_zip_does_not_fall_back_to_1262(self):
        with tempfile.TemporaryDirectory() as d, \
             patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), \
             patch('wlre.services.world.runtime_1275.resource_dir',
                   return_value=Path(d)):
            maps=SmallMaps()
            self.assertFalse(maps.entries)
            self.assertIsNone(maps.image(12910))

    def test_bundle_pin_failure_before_unity_decode(self):
        from tools.resources.export_1275_visuals import (
            select_bundle, VisualResourceError)
        with self.assertRaises(VisualResourceError):
            select_bundle([],{'target_revision':1275,'bundles':[]},'icons')


if __name__=='__main__':
    unittest.main()


class VisualCacheValidation(unittest.TestCase):
    def verify(self,path):
        with patch.dict(RESOURCE_SOURCES,{'smallmaps':(*RESOURCE_SOURCES['smallmaps'][:3],1)}):
            return verify_private_cache(path,'smallmaps')
    def rewrite(self,path,entry,value,*,update_hash=False):
        with ZipFile(path) as z:files={name:z.read(name) for name in z.namelist()}
        files[entry]=value
        if update_hash:
            manifest=json.loads(files['manifest.json'])
            manifest['images'][entry]=hashlib.sha256(value).hexdigest()
            files['manifest.json']=json.dumps(manifest).encode()
        with ZipFile(path,'w') as z:
            for name,raw in files.items():z.writestr(name,raw)
    def test_matching_hash_does_not_make_non_png_valid(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'cache.zip';write_fixture(path,'smallmaps',['SmallMap2D_12910.png'])
            self.rewrite(path,'SmallMap2D_12910.png',b'not PNG',update_hash=True)
            with self.assertRaises(VisualResourceError):self.verify(path)
    def test_index_model_name_must_match_png_entry(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'cache.zip';write_fixture(path,'smallmaps',['SmallMap2D_12910.png'])
            self.rewrite(path,'image_index.json',json.dumps([{'name':'SmallMap2D_13216','entry':'SmallMap2D_12910.png'}]).encode())
            with self.assertRaises(VisualResourceError):self.verify(path)
    def test_non_object_manifest_has_public_validation_error(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'cache.zip';write_fixture(path,'smallmaps',['SmallMap2D_12910.png'])
            self.rewrite(path,'manifest.json',b'[]')
            with self.assertRaises(VisualResourceError):self.verify(path)
    def test_invalid_index_row_has_public_validation_error(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'cache.zip';write_fixture(path,'smallmaps',['SmallMap2D_12910.png'])
            self.rewrite(path,'image_index.json',b'[null]')
            with self.assertRaises(VisualResourceError):self.verify(path)
