import copy
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from wlre.services.world.official_movement import OfficialMovementAdapter
from wlre.services.world.navigation import NavigationError
from wlre.services.world.navigation_preview import PreviewMesh, PreviewRepository
from wlre.services.world import navigation_database as database, astar_cache
from test_review_astar_cache import archive

KEY = 'b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6'


def runtime():
    return SimpleNamespace(catalog_identity=SimpleNamespace(key=KEY),
                           stages={10001:dict(model_id=10001,map_height=1000)})


def mesh(*, slope=False, water=False, middle_floor=False):
    vertices=[[0,0,0],[1000,0,0],[0,0,1000],[1000,10 if slope else 0,1000]]
    faces=[[0,1,2],[1,3,2]]
    metadata=[[0,1 | ((2 << 19) if water else 0)]]*2
    connections=[[[1,10,1]],[[0,10,2]]]
    if middle_floor:
        vertices.extend([[400,500,400],[600,500,400],[500,500,650]])
        faces.append([4,5,6]);metadata.append([0,1]);connections.append([])
    result=dict(mesh=dict(tiles=[dict(vertices_b_int3=vertices,triangles=faces,node_metadata=metadata)]),
                connections=connections)
    value=PreviewMesh(result);value.scene_id='M10001'
    return value


class OfficialMovementAdapterTests(unittest.TestCase):
    def fake(self, value=None):
        current=runtime()
        self.enterContext(patch.object(PreviewRepository,'load',return_value=(value or mesh(),[0,0,0])))
        adapter=OfficialMovementAdapter(runtime_getter=lambda:current)
        return current,adapter

    def route(self, adapter, **kwargs):
        return adapter.route(None,10001,(10,990),(90,910),**kwargs)

    def test_flat_land_route_and_steps_do_not_claim_live_acceptance(self):
        _,adapter=self.fake()
        result=self.route(adapter)
        self.assertEqual(result['execution_policy'],'bounded_official_land')
        self.assertFalse(result['can_send_packets'])
        self.assertFalse(result['live_movement_verified'])
        self.assertFalse(result['runtime_obstacles_applied'])
        self.assertTrue(adapter.validate_route(result))
        for a,b in zip(result['points'],result['points'][1:]):
            self.assertTrue(adapter.validate_step(a,b))
        self.assertEqual(adapter.to_navigation(10001,10,990),(100,100))
        self.assertEqual(adapter.to_packet(10001,100,100),(10,990))
        self.assertEqual(adapter.mapping(10001)[0]['offset_y'],1000)

    def test_forged_mutated_and_previous_route_are_rejected(self):
        _,adapter=self.fake();result=self.route(adapter)
        with self.assertRaises(NavigationError):adapter.validate_route(copy.deepcopy(result))
        result['points'][0]=(0,0,0)
        with self.assertRaises(NavigationError):adapter.validate_route(result)
        first=self.route(adapter);self.route(adapter)
        with self.assertRaises(NavigationError):adapter.validate_route(first)

    def test_failed_new_request_invalidates_previous_contract(self):
        _,adapter=self.fake();first=self.route(adapter)
        with self.assertRaises(NavigationError):adapter.route(None,99999,(10,990),(90,910))
        with self.assertRaises(NavigationError):adapter.validate_route(first)

    def test_stale_navigation_and_replaced_runtime_are_rejected(self):
        current,adapter=self.fake();state={'scene':10001,'revision':1,'stale':False}
        route=self.route(adapter,navigation_state=state)
        state['revision']=2
        with self.assertRaises(NavigationError):adapter.validate_route(route)
        state['stale']=True
        with self.assertRaises(NavigationError):self.route(adapter,navigation_state=state)
        self.route(adapter)
        current.stages[10001]['map_height']=1001
        self.assertFalse(adapter.is_current())
        with self.assertRaises(NavigationError):adapter.validate_step((100,0,100),(200,0,200))
        new=runtime();adapter=OfficialMovementAdapter(runtime_getter=lambda:new)
        new=copy.deepcopy(new)
        self.assertFalse(adapter.is_current())

    def test_no_runtime_unknown_version_or_house(self):
        with self.assertRaises(NavigationError):OfficialMovementAdapter(runtime_getter=lambda:None)
        current=runtime();current.catalog_identity.key='0'*64
        with self.assertRaises(NavigationError):OfficialMovementAdapter(runtime_getter=lambda:current)
        _,adapter=self.fake()
        with self.assertRaisesRegex(NavigationError,'僅支援進入與離開'):
            adapter.mapping(63501)

    def test_slope_water_and_wrong_height_fail_closed(self):
        for candidate in (mesh(slope=True),mesh(water=True)):
            with self.subTest(candidate=candidate):
                _,adapter=self.fake(candidate)
                with self.assertRaises(NavigationError):self.route(adapter)
        _,adapter=self.fake()
        with self.assertRaisesRegex(NavigationError,'高度'):
            self.route(adapter,start_height=99)

    def test_middle_of_path_overlapping_floor_rejected_even_with_height(self):
        _,adapter=self.fake(mesh(middle_floor=True))
        with self.assertRaisesRegex(NavigationError,'多層'):
            self.route(adapter,start_height=0,end_height=0)
        with self.assertRaisesRegex(NavigationError,'多個高度'):
            adapter.route(None,10001,(50,950),(90,910),start_height=0)

    def test_packet_rounding_or_shortcut_cannot_leave_corridor(self):
        _,adapter=self.fake();self.route(adapter)
        for a,b in (((100,0,100),(1100,0,100)),((100,0,100),(200,1,200))):
            with self.assertRaises(NavigationError):adapter.validate_step(a,b)
        with self.assertRaises(NavigationError):adapter.to_navigation(10001,-1,990)
        with self.assertRaises(NavigationError):adapter.to_navigation(10001,float('nan'),990)

    def test_step_cannot_reverse_a_one_way_portal_inside_same_geometry(self):
        candidate=mesh()
        candidate.adjacency[1].pop(0)
        candidate.serialized_connections[1]=[]
        _,adapter=self.fake(candidate)
        self.route(adapter)
        self.assertTrue(adapter.validate_step((100,0,100),(900,0,900)))
        with self.assertRaisesRegex(NavigationError,'連線方向'):
            adapter.validate_step((900,0,900),(100,0,100))

    def test_geometry_work_quotas_fail_closed(self):
        from wlre.services.world import official_movement
        _,adapter=self.fake()
        with patch.object(official_movement,'MAX_MESH_FACES',1):
            with self.assertRaisesRegex(NavigationError,'面數配額'):
                self.route(adapter)
        with patch.object(official_movement,'MAX_GEOMETRY_CHECKS',1):
            with self.assertRaisesRegex(NavigationError,'運算配額'):
                self.route(adapter)

    def test_real_database_missing_corruption_and_seed_independence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);current=runtime()
            adapter=OfficialMovementAdapter(runtime_getter=lambda:current,root=root)
            with self.assertRaisesRegex(NavigationError,'尚未同步'):adapter.mapping(10001)
            raw=archive();digest=hashlib.sha256(raw).hexdigest()
            with (patch.object(database,'REVIEWED_MODELS',{10001:digest}),
                  patch.object(astar_cache,'REVIEWED_CACHES',{digest}),
                  patch('wlre.storage.bundled_database.load_bundled_bytes',side_effect=AssertionError('seed read'))):
                database.import_cache(database.database_path(root),KEY,10001,raw,{'source':'synthetic'})
                result=adapter.route(None,10001,(10,990),(20,980))
                self.assertTrue(adapter.validate_route(result))
                import sqlite3
                with sqlite3.connect(database.database_path(root)) as db:
                    db.execute('UPDATE navigation_snapshots SET raw=?',(b'corrupt',))
                with self.assertRaisesRegex(ValueError,'integrity'):
                    adapter.route(None,10001,(10,990),(20,980))
                with self.assertRaises(NavigationError):adapter.validate_route(result)


if __name__=='__main__':unittest.main()
