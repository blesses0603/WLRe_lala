"""Keep original labels/effects without interpreting text as a warp instruction."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_boundary_portals import eve_fixture, marker, links, stages
from wlre.services.world.doors_1275 import parse_verified_doors
from wlre.services.world.boundary_portals import boundary_portal_bindings
from wlre.services.world.portals import Portals
from wlre.services.world.portal_inspection_1275 import portal_inspection_text
from wlre.services.world.portal_travel import PortalTravel
from wlre.core.state import State


def name_field(text):
    raw=text.encode('cp950')
    assert len(raw)<=20
    return raw.ljust(20,b'\0')


class PortalEventEvidenceTests(unittest.TestCase):
    def test_names_conditions_and_signed_effects_survive_actual_decoder(self):
        condition=struct.pack('<BBHHHBIBII',1,5,6,7,8,9,0xffffffff,1,10,11)
        effect=struct.pack('<BBHHHBiBII',2,3,4,5,6,7,-123,0,8,9)
        event=struct.pack('<HB',7,2)+name_field('門事件甲')+b'\x01'+condition+b'\x01'+effect
        raw=eve_fixture(events=[event])
        common=24+4+2+2+2
        self.assertEqual(raw[common:common+20],bytes(20))
        raw=raw[:common]+name_field('往獅子島')+raw[common+20:]
        door,=parse_verified_doors(raw)[60000]
        self.assertEqual(door['name'],'往獅子島')
        self.assertTrue(door['name_valid'])
        record,=door['touch_event_records']
        self.assertEqual(record['name'],'門事件甲')
        self.assertEqual(record['index'],7)
        self.assertEqual(record['conditions'][0]['data']['para_value'],0xffffffff)
        self.assertEqual(record['conditions'][0]['results'][0]['para_value'],-123)
        self.assertFalse(record['destination_decoded'])

    def test_invalid_name_does_not_discard_geometry_or_fabricate_a_label(self):
        raw=eve_fixture();common=34
        raw=raw[:common]+b'\xff'+bytes(19)+raw[common+20:]
        door,=parse_verified_doors(raw)[60000]
        self.assertIsNone(door['name'])
        self.assertFalse(door['name_valid'])
        self.assertEqual(door['name_bytes'],'ff')
        self.assertEqual(door['touch_event_ids'],[7])

    def test_conflicting_text_kept_for_inspection_never_changes_packet_or_destination(self):
        doors=parse_verified_doors(eve_fixture())
        doors[60000][0]['name']='往獅子島'
        positions,targets=boundary_portal_bindings(
            marker((60000,2,0,3,60,1100,13,0)),links(),doors,stages())
        runtime=SimpleNamespace(revision=1286,doors=doors,portal_positions=positions,
            portal_destinations=targets,scene_names={60000:'北島－北',58001:'航海大地圖'},
            portal_names={(60000,3):'甲蟲島'})
        with patch('wlre.services.world.runtime_1275.baseline_revision',return_value='1286'), \
             patch('wlre.services.world.catalog_source_policy.official_runtime',return_value=runtime):
            catalog=Portals()
        row,=catalog.for_scene(60000)
        self.assertEqual(row['name'],'前往 航海大地圖(58001)')
        self.assertEqual(row['official_name'],'甲蟲島')
        self.assertEqual(row['door_event_name'],'往獅子島')
        detail=portal_inspection_text(row)
        for text in ('已配對目的地：航海大地圖(58001)','原地圖標籤：甲蟲島',
                     '門容器原名：往獅子島','實際門編號 3','觸碰事件 7','效果語意尚未獨立核對'):
            self.assertIn(text,detail)
        state=State();state.player.update(role_id=42,scene=60000,x=120,y=4400)
        service=PortalTravel(catalog)
        with patch('wlre.services.world.portal_policy.smallmaps',
                   return_value=SimpleNamespace(has_image=lambda sid:True)):
            packet,=service.start_direct(state,Mock(),row['id'],10)
        self.assertEqual(packet.payload,struct.pack('<H',3))
        service.observe(dict(type='position_snapshot',role_id=42,scene=60012,x=100,y=200),state,Mock())
        self.assertEqual(state.portal_travel['status'],'different_map')
        self.assertEqual(state.portal_travel['arrival']['scene'],60012)
