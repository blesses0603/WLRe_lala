"""Maritime links and actual event containers have independent identities."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from wlre.services.world.boundary_portals import reconcile_touch_bindings
from wlre.services.world.portal_links_1275 import verified_portal_positions, verified_portal_destinations
from wlre.services.world.portal_dedup_1275 import collapse_portal_destinations
from wlre.services.world.portals import Portals
from wlre.services.world.portal_travel import PortalTravel
from wlre.core.state import State
from unittest.mock import Mock


class SailingDoorIdentityTests(unittest.TestCase):
    def setUp(self):
        self.stages={58001:dict(pos_x_ratio=1,pos_y_ratio=1,map_width=10000,
            map_height=10000,small_offset_x=0,small_offset_y=0),60012:{},12601:{}}
        self.links=('事件ID=58001\n'
            '原場景位置[X:1000,Y:1000][60012][X:100,Y:200]\n'
            '原場景位置[X:2000,Y:2000][12601][X:300,Y:400]\n'
            '原場景位置[X:3000,Y:3000][60012][X:500,Y:600]\n').encode('utf-16-le')
        self.raw=struct.pack('<i',3)+b''.join(struct.pack('<HBHIHHIB',58001,2,0,i,1,1,i,0)
                                              for i in (1,2,3))
        def door(index,p):
            return dict(index=index,x=p//20,y=p//20,right=p//20+2,bottom=p//20+2,
                        sign_type=1,sign_x=0,sign_y=0,event_ids=[index],touch_event_ids=[index])
        self.doors={58001:[door(44,1000),door(77,2000),door(45,3000),
                          door(1,4000),door(2,5000),door(3,6000)]}

    def bind(self):
        positions=verified_portal_positions(self.raw,self.links,self.doors,self.stages)
        targets=verified_portal_destinations(self.raw,self.links,self.doors,self.stages)
        self.assertEqual(set(targets),{(58001,1),(58001,2),(58001,3)})
        reconcile_touch_bindings(self.raw,self.links,self.doors,self.stages,positions,targets)
        return positions,targets

    def test_replaces_false_ordinal_joins_and_groups_without_changing_event_ids(self):
        positions,targets=self.bind()
        self.assertEqual({key[1]:row['link_index'] for key,row in targets.items()}, {44:1,77:2,45:3})
        runtime=SimpleNamespace(revision=1286,doors=self.doors,portal_positions=positions,
            portal_destinations=targets,scene_names={58001:'航海大地圖',60012:'台灣',12601:'曼谷港'},
            portal_names={(58001,1):'台灣入口',(58001,2):'曼谷港入口',(58001,3):'台灣另一入口'},
            portal_display_destinations={(58001,44):12601})
        with patch('wlre.services.world.runtime_1275.baseline_revision',return_value='1286'), \
             patch('wlre.services.world.catalog_source_policy.official_runtime',return_value=runtime):
            catalog=Portals()
        all_rows=catalog.for_scene(58001)
        bound=[row for row in all_rows if row['direct_eligible']]
        self.assertEqual(len(all_rows),6)
        self.assertEqual(len(bound),3)
        shown=collapse_portal_destinations(bound)
        self.assertEqual({row['direct_door_index'] for row in shown},{44,77})
        taiwan=next(row for row in shown if row['destination']==60012)
        self.assertEqual(taiwan['official_name'],'台灣入口')
        self.assertEqual(taiwan['display_destination_label'],'台灣(60012)')
        self.assertEqual((taiwan['x'],taiwan['y']),(1000,1000))
        self.assertEqual(taiwan['link_index'],1)
        state=State();state.player.update(role_id=42,scene=58001,x=1000,y=1000)
        with patch('wlre.services.world.portal_policy.smallmaps',
                   return_value=SimpleNamespace(has_image=lambda sid:True)):
            packet,=PortalTravel(catalog).start_direct(state,Mock(),taiwan['id'],10)
        self.assertEqual(packet.payload,struct.pack('<H',44))
        self.assertEqual(state.player['scene'],58001)

    def test_missing_touch_evidence_cannot_fall_back_to_same_number_marker(self):
        for row in self.doors[58001]:row['touch_event_ids']=[]
        self.assertEqual(self.bind(),({},{}))

    def test_two_links_claiming_one_actual_door_are_not_silently_overwritten(self):
        self.links=self.links.decode('utf-16-le').replace('X:3000,Y:3000','X:1000,Y:1000').encode('utf-16-le')
        positions,targets=self.bind()
        self.assertEqual(set(targets),{(58001,77)})
        self.assertEqual(set(positions),set(targets))

    def test_actual_door_ids_can_overlap_other_link_ordinals(self):
        self.doors[58001]=self.doors[58001][:3]
        for row,index in zip(self.doors[58001],(2,3,1)):row['index']=index
        positions={};targets={}
        reconcile_touch_bindings(self.raw,self.links,self.doors,self.stages,positions,targets)
        self.assertEqual({key[1]:row['link_index'] for key,row in targets.items()}, {2:1,3:2,1:3})
