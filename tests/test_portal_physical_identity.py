"""Every scene must bind actual physical doors, not matching ordinal numbers."""
import struct
import unittest
from copy import deepcopy
from wlre.services.world.boundary_portals import reconcile_touch_bindings, reconcile_route_conflicts
from wlre.services.world.portal_links_1275 import verified_portal_positions, verified_portal_destinations


class AllScenePortalIdentityTests(unittest.TestCase):
    def setUp(self):
        self.stages={11016:dict(pos_x_ratio=1,pos_y_ratio=1,map_width=10000,map_height=10000,
                                small_offset_x=0,small_offset_y=0),11017:{},11018:{}}
        self.raw=struct.pack('<i',2)+b''.join(struct.pack('<HBHIHHIB',11016,2,0,i,1,1,1,0) for i in (1,2))
        self.links=('事件ID=11016\n原場景位置[X:1000,Y:1000][11017][X:100,Y:200]\n'
                    '原場景位置[X:2000,Y:2000][11018][X:300,Y:400]\n').encode('utf-16-le')
        def door(index,p):
            return dict(index=index,x=p//20,y=p//20,right=p//20+2,bottom=p//20+2,
                        sign_type=1,sign_x=0,sign_y=0,touch_event_ids=[7])
        self.doors={11016:[door(1,2000),door(2,1000)]}

    def bind(self):
        positions={};targets={}
        reconcile_touch_bindings(self.raw,self.links,self.doors,self.stages,positions,targets)
        return positions,targets

    def test_normal_scene_swapped_numbers_never_pick_ordinal_destination(self):
        positions,targets=self.bind()
        self.assertEqual({i:row['destination'] for (_,i),row in targets.items()}, {1:11018,2:11017})
        self.assertEqual(targets[11016,2]['link_index'],1)
        self.assertEqual(positions[11016,2]['x'],1000)
        self.assertEqual(verified_portal_destinations(self.raw,self.links,self.doors,self.stages),targets)
        self.assertEqual(verified_portal_positions(self.raw,self.links,self.doors,self.stages),positions)

    def test_same_numbers_and_marker_cannot_authorize_unrelated_geometry(self):
        self.doors[11016]=[dict(self.doors[11016][0],x=300,y=300,right=302,bottom=302)]
        positions={(11016,1):{'x':1000}}
        targets={(11016,1):{'destination':11017}}
        reconcile_touch_bindings(self.raw,self.links,self.doors,self.stages,positions,targets)
        self.assertEqual((positions,targets),({},{}))
        self.assertEqual(verified_portal_destinations(self.raw,self.links,self.doors,set(self.stages)),{})

    def test_prefab_portal_requires_exact_anchor_never_an_invented_radius(self):
        for kind in (2,3,5):
            with self.subTest(sign_type=kind):
                self.doors[11016]=[dict(index=9,x=51,y=51,sign_type=kind,
                                       sign_x=0,sign_y=0,touch_event_ids=[7])]
                positions,targets=self.bind()
                self.assertEqual(set(targets),{(11016,9)})
                self.assertEqual(targets[11016,9]['destination'],11017)
                self.assertEqual(targets[11016,9]['binding_kind'],'unique_door_anchor')
                self.doors[11016][0]['sign_x']=1
                self.assertEqual(self.bind(),({},{}))

    def test_unknown_target_at_same_door_still_exposes_ambiguity(self):
        self.links=self.links.decode('utf-16-le').replace('X:2000,Y:2000','X:1000,Y:1000').replace('[11018]','[65000]').encode('utf-16-le')
        self.assertEqual(self.bind(),({},{}))

    def test_conditional_targets_do_not_choose_a_convenient_first_row(self):
        self.links=self.links.decode('utf-16-le').replace('X:2000,Y:2000','X:1000,Y:1000').encode('utf-16-le')
        self.assertEqual(self.bind(),({},{}))

    def test_independent_route_conflict_revokes_only_same_physical_point(self):
        route=dict(scene=11016,x=1000,y=1000,destination=11018,position_verified=True)
        for change,expected in (({}, {1}),({'destination':11017},{1,2}),
                                ({'scene':11019},{1,2}),({'x':1001},{1,2}),
                                ({'position_verified':False},{1,2})):
            with self.subTest(change=change):
                positions,targets=self.bind()
                raw=deepcopy(route)
                evidence={(11016,1):{'issues':()}}
                reconcile_route_conflicts(positions,targets,[dict(route,**change)],evidence)
                if expected == {1}:
                    self.assertEqual(evidence[11016,1]['destination_candidates'],(11017,11018))
                    self.assertIn('conflicting_official_destinations',evidence[11016,1]['issues'])
                else:
                    self.assertEqual(evidence[11016,1],{'issues':()})
                self.assertEqual({idx for sid,idx in targets},expected)
                self.assertEqual(set(positions),set(targets))
                self.assertEqual(route,raw)
