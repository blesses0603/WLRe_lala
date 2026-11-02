"""Coastal EveDoorLinks need actual touch-region proof, not fake marker IDs."""
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from wlre.core.state import State
from wlre.features.portals.panel import PortalInteractionMixin
from wlre.network.wire import Writer
from wlre.services.world.boundary_portals import boundary_portal_bindings, touch_bounds
from wlre.services.world.doors_1275 import parse_verified_doors, DoorSourceError
from wlre.services.world.portal_travel import PortalTravel
from wlre.services.world.portals import Portals


def marker(*rows):
    return struct.pack('<i',len(rows))+b''.join(struct.pack('<HBHIHHIB',*r) for r in rows)


def stages():
    return {60000:{'pos_x_ratio':2,'pos_y_ratio':4,'map_width':9000,'map_height':15000,
                   'small_offset_x':0,'small_offset_y':0},
            58001:{'pos_x_ratio':2,'pos_y_ratio':4},11016:{},12000:{}}


def links():
    return ('事件ID=60000\n原場景位置[X:1759,Y:2701][11016][X:1,Y:2]\n'
            '原場景位置[X:2961,Y:3141][12000][X:1,Y:2]\n'
            '原場景位置[X:60,Y:1100][58001][X:7453,Y:8461]\n').encode('utf-16-le')


def door(**kw):
    return dict(index=3,x=1,y=1,right=8,bottom=112,sign_type=4,sign_x=0,sign_y=0,
                col_x=0,col_y=0,col_z=0,event_ids=[7],touch_event_ids=[7],**kw)


def eve_fixture(*,occur=2,events=None):
    # Eleven full v115 sections, including real NewDoor/NewEvent tails.
    common=bytes(20)+b'\x00'+struct.pack('<II',1,1)+b'\x01\x07\x00\x00'
    d=struct.pack('<H',3)+common+struct.pack('<IIBIIIII',8,112,4,0,0,0,0,0)
    event=(struct.pack('<HB',7,occur)+bytes(20)+b'\x01'+bytes(22)+b'\x02'+bytes(44))
    sections=[b'\x00\x00',b'\x01\x00'+d,b'\x00\x00',b'\x00\x00',
              struct.pack('<H',len(events or [event]))+b''.join(events or [event])]
    sections += [b'\x00\x00']*6
    offset=4;table=[]
    for section in sections:table.append(offset);offset+=len(section)
    scene=struct.pack('<HH',99,115)+b''.join(sections)+struct.pack('<11I',*table)
    return bytes(8)+struct.pack('<IHHII',1,60000,99,24,len(scene))+scene


class BoundaryPortalTests(unittest.TestCase):
    def setUp(self):
        self.doors=parse_verified_doors(eve_fixture())
        self.stages=stages();self.raw=marker()

    def bind(self):return boundary_portal_bindings(self.raw,links(),self.doors,self.stages)

    def test_decoder_preserves_real_geometry_and_player_touch_events(self):
        d,=self.doors[60000]
        self.assertEqual((d['index'],d['right'],d['bottom'],d['sign_type']),(3,8,112,4))
        self.assertEqual(d['touch_event_ids'],[7])
        self.assertEqual(parse_verified_doors(eve_fixture(occur=1))[60000][0]['touch_event_ids'],[])
        self.assertEqual(touch_bounds(d,self.stages[60000]),(0,0,280,8880))

    def test_duplicate_or_truncated_event_data_is_rejected(self):
        e=struct.pack('<HB',7,2)+bytes(20)+b'\x00'
        with self.assertRaises(DoorSourceError):parse_verified_doors(eve_fixture(events=[e,e]))
        raw=eve_fixture()
        with self.assertRaises(DoorSourceError):parse_verified_doors(raw[:-80])

    def test_grid_cell_offset_and_sign_offset_follow_lua_in_both_axes(self):
        self.assertEqual(touch_bounds({**door(),'sign_x':3,'sign_y':5},self.stages[60000]),
                         (6,20,286,8900))
        self.assertIsNone(touch_bounds({**door(),'sign_type':True},self.stages[60000]))

    def test_binding_uses_current_destination_instead_of_a_fixed_world_map_id(self):
        self.stages[59002]=self.stages.pop(58001)
        raw=links().decode('utf-16-le').replace('[58001]','[59002]').encode('utf-16-le')
        _,targets=boundary_portal_bindings(self.raw,raw,self.doors,self.stages)
        self.assertEqual(targets[60000,3]['destination'],59002)

    def test_sailing_link_without_normal_marker_binds_real_door_three(self):
        positions,targets=self.bind()
        self.assertEqual(set(positions),{(60000,3)})
        self.assertEqual((positions[60000,3]['x'],positions[60000,3]['y']),(120,4400))
        self.assertEqual(targets[60000,3]['destination'],58001)
        self.assertTrue(targets[60000,3]['matched_touch_region'])
        self.assertFalse(targets[60000,3]['matched_stage_map'])
        self.assertFalse(targets[60000,3]['trigger_verified'])

    def test_unknown_target_ratios_or_geometry_never_bind(self):
        for mutation in ('target','ratio','geometry'):
            self.stages=stages()
            if mutation=='target':self.stages.pop(58001)
            elif mutation=='ratio':self.stages[60000]['pos_x_ratio']=0
            else:self.stages[60000].pop('map_height')
            with self.subTest(mutation=mutation):self.assertEqual(self.bind(),({},{}))

    def test_uncertain_or_conflicting_touch_regions_remain_disabled(self):
        for change in ({'touch_event_ids':[]},{'sign_type':5},{'right':1},
                       {'x':-1},{'sign_x':65535}):
            self.doors={60000:[{**door(),**change}]}
            with self.subTest(change=change):self.assertEqual(self.bind(),({},{}))
        self.doors={60000:[door(),{**door(),'index':4}]}
        self.assertEqual(self.bind(),({},{}))
        self.doors={60000:[door(),door()]}
        self.assertEqual(self.bind(),({},{}))

    def test_maritime_marker_does_not_override_actual_touch_identity(self):
        row=(60000,2,0,3,60,1100,0,0)
        for raw in (marker(row),marker(row,row)):
            self.raw=raw
            positions,targets=self.bind()
            self.assertEqual(set(targets),{(60000,3)})
            self.assertTrue(targets[60000,3]['matched_touch_region'])

    def test_audit_recognizes_boundary_proof_without_fabricating_normal_marker(self):
        from wlre.services.world.portal_coverage import audit_portal_coverage
        positions,targets=self.bind()
        report=audit_portal_coverage(self.doors,self.stages,self.raw,links(),positions,targets)
        scene=next(r for r in report['scenes'] if r['scene']==60000)
        row=next(r for r in scene['details'] if r['index']==3)
        self.assertEqual(row['category'],'boundary_portal')
        self.assertEqual(row['issues'],[])

    def test_hidden_destination_is_not_reused_as_a_door_id(self):
        self.raw=marker((60000,3,0,58001,60,1100,1,0))
        positions,targets=self.bind()
        self.assertEqual(set(targets),{(60000,3)})
        self.assertNotIn((60000,58001),positions)

    def test_link_three_binds_door_nine_through_catalog_and_packet(self):
        self.doors={60000:[{**door(),'index':9}]}
        positions,targets=self.bind()
        self.assertEqual(set(targets),{(60000,9)})
        self.assertEqual(targets[60000,9]['link_index'],3)
        catalog=self.catalog();row,=catalog.for_scene(60000)
        self.assertEqual((row['index'],row['link_index'],row['direct_door_index']),(9,3,9))
        self.assertIn('航海大地圖',row['name'])
        state=State();state.player.update(role_id=42,scene=60000,x=120,y=4400)
        with patch('wlre.services.world.portal_policy.smallmaps',
                   return_value=SimpleNamespace(has_image=lambda sid:True)):
            packet,=PortalTravel(catalog).start_direct(state,Mock(),row['id'],10)
        self.assertEqual(packet.payload,Writer().u16(9).build())
        self.assertEqual(state.player['scene'],60000)
        from wlre.services.world.portal_coverage import audit_portal_coverage
        audit=audit_portal_coverage(self.doors,self.stages,self.raw,links(),positions,targets)
        scene=next(r for r in audit['scenes'] if r['scene']==60000)
        detail=next(r for r in scene['details'] if r['index']==9)
        self.assertEqual((detail['link_index'],detail['issues']),(3,[]))
        self.assertFalse(any(r['index']==3 for r in scene['details']))

    def catalog(self):
        positions,targets=self.bind()
        runtime=SimpleNamespace(revision=1286,doors=self.doors,portal_positions=positions,
            portal_destinations=targets,scene_names={60000:'北島－北',58001:'航海大地圖'})
        with patch('wlre.services.world.runtime_1275.baseline_revision',return_value='1286'), \
             patch('wlre.services.world.catalog_source_policy.official_runtime',return_value=runtime):
            return Portals()

    def test_catalog_and_ui_enable_only_bound_coastal_door(self):
        catalog=self.catalog();row,=catalog.for_scene(60000)
        self.assertTrue(row['direct_eligible']);self.assertEqual(row['direct_door_index'],3)
        self.assertIn('航海大地圖',row['name']);self.assertIn('觸碰',row['direct_note'])
        self.assertEqual(row['trigger_bounds'],(0,0,280,8880))
        from wlre.services.world.portal_inspection_1275 import portal_inspection_text
        self.assertIn('海岸碰撞範圍',portal_inspection_text(row))
        page=PortalInteractionMixin();page.selected_portal=row
        page.maps=SimpleNamespace(has_image=lambda sid:sid==58001)
        page.state={'player':{'scene':60000}};page.selected_id=60000
        page.projection=SimpleNamespace(**row['projection_guard'],packet_to_pixel=lambda x,y:(10,20))
        page.portal_go=Mock();page.portals=catalog;page.on_portal=Mock();page.portal_status=Mock()
        page.update_portal_button();self.assertEqual(page.portal_go.configure.call_args.kwargs['state'],'normal')
        self.assertTrue(page.go_portal());page.on_portal.assert_called_once_with(row['id'])

    def test_actual_request_uses_door_id_once_and_waits_for_server(self):
        catalog=self.catalog();row,=catalog.for_scene(60000)
        state=State();state.player.update(role_id=42,scene=60000,x=3714,y=10408)
        service=PortalTravel(catalog);movement=Mock()
        with patch('wlre.services.world.portal_policy.smallmaps',
                   return_value=SimpleNamespace(has_image=lambda sid:sid==58001)):
            packet,=service.start_direct(state,movement,row['id'],10)
            self.assertEqual(packet.payload,Writer().u16(3).build())
            self.assertEqual((packet.main,packet.sub),(20,8))
            self.assertEqual(service.start_direct(state,movement,row['id'],11),[])
        self.assertEqual(state.player['scene'],60000)
        self.assertEqual(state.portal_travel['status'],'awaiting_map')
        service.observe({'type':'position_snapshot','role_id':42,'scene':58001,'x':14906,'y':33844},state,movement)
        self.assertEqual(state.portal_travel['status'],'completed')
        self.assertEqual(state.portal_travel['arrival']['scene'],58001)

    def test_real_projection_single_click_selects_and_double_click_requests_exit(self):
        from wlre.services.world.smallmaps import Projection
        from wlre.services.world.portals import portal_map_pixel
        from wlre.features.minimap.buttons import MinimapPickMixin
        catalog=self.catalog();row,=catalog.for_scene(60000)
        projection=Projection({**self.stages[60000],'offset_y':15000},(0,0,0))
        x,y=portal_map_pixel(row,projection)
        page=PortalInteractionMixin();page.projection=projection
        page.portal_rows=[row];page.screen_pixel=lambda x,y:(x,y)
        page.select_portal=Mock();page.selected_portal=row;page.portals=catalog
        page.maps=SimpleNamespace(has_image=lambda sid:True)
        page.state={'player':{'scene':60000}};page.on_portal=Mock();page.portal_status=Mock()
        event=SimpleNamespace(x=x,y=y)
        self.assertFalse(MinimapPickMixin.pick(page,event))
        page.on_portal.assert_not_called()
        self.assertEqual(MinimapPickMixin.double_pick(page,event),'break')
        page.on_portal.assert_called_once_with(row['id'])

    def test_rejection_or_timeout_never_reports_success_or_retries(self):
        for outcome in ('reject','timeout'):
            catalog=self.catalog();row,=catalog.for_scene(60000)
            state=State();state.player.update(role_id=42,scene=60000,x=3714,y=10408)
            service=PortalTravel(catalog);movement=Mock()
            with patch('wlre.services.world.portal_policy.smallmaps',
                       return_value=SimpleNamespace(has_image=lambda sid:True)):
                service.start_direct(state,movement,row['id'],10)
            if outcome=='reject':service.observe({'type':'event_rejected','reason':'需要載具'},state,movement)
            else:self.assertEqual(service.tick(state,movement,26),[])
            self.assertIsNone(service.pending)
            self.assertNotEqual(state.portal_travel['status'],'completed')
            self.assertEqual(service.tick(state,movement,30),[])


if __name__=='__main__':unittest.main()
