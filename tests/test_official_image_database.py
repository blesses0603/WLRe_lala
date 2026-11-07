from contextlib import closing
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
from wlre.services.world.smallmap_database import import_images,image_paths,PREFIX
from wlre.services.world.smallmaps import SmallMaps


class OfficialImageDatabase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'images.sqlite3'
        self.paths=(PREFIX+'SmallMap2D_123.png',)
        self.decode=Mock(side_effect=lambda:iter([(self.paths[0],Image.new('RGBA',(1024,1024),'blue'))]))
    def load(self,key='a',inputs=None,decode=None):
        return import_images(self.path,key,inputs or {'verified':'source'},self.paths,decode or self.decode)
    def test_atomic_snapshot_hit_and_corrupt_derived_repair(self):
        images=self.load();original=images.png(123)
        self.load();self.assertEqual(self.decode.call_count,1)
        with closing(sqlite3.connect(self.path)) as db, db:db.execute('UPDATE map_images SET png=?',(b'broken',))
        with self.assertRaises(ValueError):images.png(123)
        repaired=self.load();self.assertEqual(repaired.png(123),original)
        self.assertEqual(self.decode.call_count,2)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT png FROM image_history').fetchone()[0],b'broken')
    def test_failed_new_import_and_source_change_keep_previous(self):
        images=self.load();old=images.png(123)
        def broken():
            yield self.paths[0],Image.new('RGBA',(1024,1024),'red')
            raise ValueError('truncated source')
        with self.assertRaises(ValueError):self.load('b',decode=broken)
        with self.assertRaises(ValueError):self.load(inputs={'verified':'changed'})
        self.assertEqual(images.png(123),old)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT catalog_key FROM image_versions').fetchall(),[('a',)])
            self.assertEqual(db.execute("SELECT count(*) FROM image_attempts WHERE status='failed'").fetchone()[0],2)
    def test_missing_duplicate_wrong_dimensions_refused(self):
        for rows in ([],[(self.paths[0],Image.new('RGBA',(2,2)))],
            [(self.paths[0],Image.new('RGBA',(1024,1024)))]*2):
            with self.subTest(count=len(rows)),self.assertRaises(ValueError):self.load(decode=lambda:iter(rows))
    def test_exact_paths_and_duplicate_models(self):
        def manifest(paths):return SimpleNamespace(index={'assets':[{'path':p} for p in paths]})
        self.assertEqual(image_paths(manifest(self.paths)),self.paths)
        for paths in ([],self.paths*2,[PREFIX+'SmallMap2D_0.png'],[PREFIX+'unknown.png']):
            with self.assertRaises(ValueError):image_paths(manifest(paths))
    def test_cold_start_stale_version_and_no_legacy_fallback(self):
        images=self.load();stage=dict(model_id=123,map_width=1000,map_height=2000,small_offset_x=12,small_offset_y=24)
        runtime=SimpleNamespace(revision=1296,catalog_identity=SimpleNamespace(key='a'),smallmaps=images,stages={7:stage})
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=runtime),patch(
                'wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=None),patch(
                'wlre.storage.bundled_database.load_bundled_bytes',side_effect=AssertionError('no ZIP')):
            maps=SmallMaps();self.assertTrue(maps.has_image(7))
            projection,model=maps.projection(7);self.assertEqual(model,'M00123')
            x,y=projection.pixel_to_packet(*projection.packet_to_pixel(321,456))
            self.assertAlmostEqual(x,321);self.assertAlmostEqual(y,456)
            self.assertEqual(maps.image(model).size,(1024,1024))
            runtime.smallmaps=None
            self.assertFalse(maps.has_image(7))
            with self.assertRaises(ValueError):maps.png_bytes(model)
            fresh=SmallMaps();self.assertFalse(fresh.has_image(7));self.assertEqual(fresh.entries,{})
    def test_projection_sentinel_and_invalid_fields(self):
        images=self.load();stage=dict(model_id=123,map_width=65535,map_height=65535,small_offset_x=12,small_offset_y=24)
        runtime=SimpleNamespace(revision=1296,catalog_identity=SimpleNamespace(key='a'),smallmaps=images,stages={7:stage})
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=runtime),patch(
                'wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=None):
            maps=SmallMaps();p,_=maps.projection(7)
            self.assertEqual(p.height,6992);self.assertAlmostEqual(p.rate,100000/6992)
            for field in ('map_width','map_height','small_offset_x','model_id'):
                previous=stage[field];stage[field]=-1
                with self.assertRaises(ValueError):maps.projection(7)
                stage[field]=previous

    def test_invalid_bundle_never_reaches_decoder_or_database(self):
        from wlre.services.world.smallmap_database import load_verified_images
        manifest=SimpleNamespace(index={'assets':[{'path':self.paths[0]}]})
        spec=SimpleNamespace(cache_path=lambda root:Path(root)/'bad')
        plan=SimpleNamespace(entries=[SimpleNamespace(action='cached',spec=spec)])
        with patch('wlre.services.official_incremental_sync.build_update_plan',return_value=plan),patch(
                'wlre.services.official_bundle_download._verified_file',return_value=False),patch(
                'wlre.services.world.unity_textasset._loader') as decode:
            with self.assertRaises(ValueError):load_verified_images(manifest,self.path.parent,self.path.parent,SimpleNamespace(key='a'))
            decode.assert_not_called()
            self.assertFalse(self.path.exists())

    def test_newer_database_schema_is_never_downgraded(self):
        self.load()
        with closing(sqlite3.connect(self.path)) as db, db:db.execute('UPDATE image_schema SET version=2')
        with self.assertRaises(ValueError):self.load()
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT version FROM image_schema').fetchall(),[(2,)])
            self.assertEqual(db.execute('SELECT count(*) FROM map_images').fetchone()[0],1)

    def test_sources_changing_during_import_roll_back(self):
        old=self.load();before=old.png(123)
        with self.assertRaises(ValueError):
            import_images(self.path,'b',{'verified':'next'},self.paths,self.decode,
                          verify_sources=Mock(side_effect=ValueError('source changed')))
        self.assertEqual(old.png(123),before)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT catalog_key FROM image_versions').fetchall(),[('a',)])

    def test_explicit_historical_zip_is_not_default_authority(self):
        import zipfile,json
        output=io.BytesIO();Image.new('RGBA',(1024,1024),'red').save(output,format='PNG')
        archive=Path(self.temp.name)/'old.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('image_index.json',json.dumps([{'name':'SmallMap2D_123','entry':'old.png'}]))
            z.writestr('old.png',output.getvalue())
        old=SmallMaps(archive,source_revision='1275')
        self.assertEqual(old.image(123).getpixel((0,0)),(255,0,0,255))
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=SimpleNamespace(smallmaps=None)):
            current=SmallMaps()
            self.assertFalse(current.has_image(123))
            with self.assertRaises(ValueError):current.image(123)
