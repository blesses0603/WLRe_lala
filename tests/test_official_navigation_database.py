import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_review_astar_cache import archive
from wlre.services.world import astar_cache as codec
from wlre.services.world import navigation_database as database
from wlre.services.world.navigation_preview import PreviewMesh, PreviewRepository
from wlre.services.world.navigation import NavigationError


class NavigationDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=database.database_path(self.root)
        self.raw=archive();self.sha=hashlib.sha256(self.raw).hexdigest();self.version='a'*64
        for target,name,value in ((codec,'REVIEWED_CACHES',{self.sha}),
                                  (database,'REVIEWED_MODELS',{10000:self.sha})):
            p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)

    def put(self,version=None):
        return database.import_cache(self.db,version or self.version,10000,self.raw,{'source':'synthetic'})

    def test_cold_start_and_exact_version(self):
        self.assertIsNone(database.load_cache(self.db,self.version,10000))
        self.put()
        self.assertIsNone(database.load_cache(self.db,'b'*64,10000))
        self.assertEqual(database.load_cache(self.db,self.version,10000)['origin'],[0,0,0])

    def test_failed_update_keeps_previous_snapshot(self):
        self.put()
        with self.assertRaises(ValueError):
            database.import_cache(self.db,self.version,10000,b'bad',{})
        database.record_failure(self.db,self.version,10000,'download failed')
        self.assertIsNotNone(database.load_cache(self.db,self.version,10000))
        self.put('b'*64)
        self.assertIsNotNone(database.load_cache(self.db,self.version,10000))

    def test_transaction_rolls_back_failed_activation(self):
        self.put()
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TRIGGER reject_activation BEFORE INSERT ON navigation_active BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.put('b'*64)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM navigation_snapshots').fetchone()[0],1)
        self.assertIsNotNone(database.load_cache(self.db,self.version,10000))

    def test_corrupt_normalized_or_raw_cache_rejected(self):
        for field,value in (('geometry','{}'),('raw',b'bad')):
            self.put()
            with sqlite3.connect(self.db) as db:db.execute(f'UPDATE navigation_snapshots SET {field}=?',(value,))
            with self.assertRaises(ValueError):database.load_cache(self.db,self.version,10000)

    def test_unknown_schema_not_replaced(self):
        self.put()
        with sqlite3.connect(self.db) as db:db.execute('UPDATE navigation_schema SET version=99')
        with self.assertRaises(ValueError):self.put()
        with self.assertRaises(ValueError):database.load_cache(self.db,self.version,10000)

    def test_no_movement_permission_or_unwalkable_route(self):
        result=self.put();mesh=PreviewMesh(result)
        route=mesh.route((10,10),(20,20))
        self.assertFalse(route['can_send_packets'])
        self.assertFalse(route['serialized_costs_applied'])
        result['mesh']['tiles'][0]['node_metadata'][0][1]=0
        with self.assertRaises(NavigationError):PreviewMesh(result).route((10,10),(20,20))

    def test_serialized_direction_and_invalid_reference(self):
        import struct
        mesh=dict(tiles=[dict(vertices_b_int3=[[0,0,0],[1000,0,0],[0,0,1000],[1000,0,1000]],
                             triangles=[[0,1,2],[1,3,2]],node_metadata=[[0,1],[0,1]])])
        parts={'graph_references.binary':struct.pack('<3i',20,10,20),
               'graph0_references.binary':struct.pack('<iiIBi',1,20,100,1,0)}
        connections=codec.decode_connections(parts,mesh)
        preview=PreviewMesh(dict(mesh=mesh,connections=connections))
        self.assertEqual(preview.route((100,100),(900,900))['faces'],[0,1])
        with self.assertRaises(NavigationError):preview.route((900,900),(100,100))
        for raw in (struct.pack('<iiIBi',1,99,100,1,0),struct.pack('<iiIBi',1,20,100,0,0),
                    parts['graph0_references.binary']+b'bad'):
            with self.assertRaises(ValueError):codec.decode_connections({**parts,'graph0_references.binary':raw},mesh)

    def test_coordinates_and_unknown_house_fail_closed(self):
        self.put()
        repository=PreviewRepository(SimpleNamespace(key=self.version),
            {10000:dict(model_id=10000,map_height=3400)},root=self.root)
        with patch('wlre.services.world.navigation_preview.REVIEWED_COORDINATE_CATALOGS',{self.version}):
            route=repository.route(10000,(1,3399),(2,3398))
            self.assertEqual(route['packet_points_xy_float'],[[1,3399],[2,3398]])
            with self.assertRaises(NavigationError):repository.route(61501,(1,1),(2,2))
        with self.assertRaises(NavigationError):repository.route(10000,(1,3399),(2,3398))

    def test_unknown_model_and_path_rejected(self):
        repository=PreviewRepository(SimpleNamespace(key=self.version),{},root=self.root)
        with self.assertRaises(ValueError):repository.load('../../x')
        with self.assertRaises(ValueError):database.import_cache(self.db,self.version,99999,self.raw,{})



class NavigationSyncTests(unittest.TestCase):
    setUp=NavigationDatabaseTests.setUp
    def test_download_budget_and_version_change_do_not_activate(self):
        from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
        from wlre.services.official_manifest_sync import ManifestSpec
        from wlre.services.world.navigation_sync import sync_model
        from unittest.mock import Mock
        manifest_file=self.root/'manifest';manifest_file.write_bytes(b'synthetic')
        revision='1296_2026_11_04_13_36_07_72'
        identity=OfficialCatalogIdentity('1.3.23','1.3.0',tuple(PackageRevision(n,revision,hashlib.sha256(b'synthetic').hexdigest(),'00000000') for n in ('DataPackage','MainPackage')))
        names=('mainpackage_scene_10000.bundle','mainpackage_scene_10000_dependency.bundle')
        index=dict(header=dict(package_name='MainPackage',file_version='2.2.5',output_name_style=1,package_version=revision),
                   assets=[dict(address='M10000',path='Assets/M10000.unity',bundle_name=names[0])],
                   bundles=[dict(name=n,file_size=20*1024*1024,file_hash='0'*32,file_crc='0'*8,dependencies=[names[1]]) for n in names])
        manifest=SimpleNamespace(spec=ManifestSpec('1.3.23','MainPackage',revision),cache_path=manifest_file,index=index)
        snapshot=dict(schema_version=1,origin='official_pc_version_endpoint',checked_at_utc='2026-11-06T00:00:00Z',assets_ready=False,data_ver='1.3.23',exe_version='1.3.0',packages={n:revision for n in ('DataPackage','MainPackage')})
        fetch=Mock(return_value=manifest_file)
        with self.assertRaisesRegex(ValueError,'budget'):
            sync_model(identity,10000,root=self.root,fetch=fetch,manifest=manifest,observe=lambda:snapshot)
        fetch.assert_not_called()
        for row in index['bundles']:row['file_size']=10
        changed={**snapshot,'data_ver':'1.3.24'}
        with patch('wlre.services.official_bundle_download._verified_file',return_value=True), patch('wlre.services.world.navigation_sync.extract_cache',return_value=(self.raw,{})):
            with self.assertRaisesRegex(ValueError,'version changed'):
                sync_model(identity,10000,root=self.root,fetch=fetch,manifest=manifest,observe=Mock(side_effect=[snapshot,changed]))
        self.assertIsNone(database.load_cache(self.db,identity.key,10000))


if __name__=='__main__':unittest.main()
