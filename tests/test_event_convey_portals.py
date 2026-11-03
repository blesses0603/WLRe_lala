"""Exercise actual v115 bytes, then catalog, marker and C20-8 boundaries."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_boundary_portals import eve_fixture, stages
from wlre.services.world.doors_1275 import parse_verified_doors, DoorSourceError
from wlre.services.world.boundary_portals import boundary_portal_bindings
from wlre.services.world.portals import Portals, marked_portals
from wlre.services.world.portal_policy import destination_problem
from wlre.services.world.portal_travel import PortalTravel
from wlre.core.state import State


def fixture(targets=(58001,), missing=False):
    condition=struct.pack('<BBHHHBIBII',1,5,30381,1,1,5,1,1,0,0)
    effects=b''.join(struct.pack('<BBHHHBiBII',i+1,1,3,96+i,0,0,0,0,0,0)
                     for i in range(len(targets)))
    event=struct.pack('<HB',7,2)+bytes(20)+b'\x01'+condition+bytes([len(targets)])+effects
    raw=eve_fixture(events=[event]);scene=raw[24:]
    offsets=list(struct.unpack_from('<11I',scene,len(scene)-44))
    conveys=(struct.pack('<H',len(targets))+b''.join(
        struct.pack('<H20sHIIBH',96+i,bytes(20),target,100,200,5,0)
        for i,target in enumerate(targets))) if not missing else b'\0\0'
    old=offsets[7]-offsets[6]
    scene=scene[:offsets[6]]+conveys+scene[offsets[7]:-44]
    delta=len(conveys)-old
    offsets=[o+delta if i>=7 else o for i,o in enumerate(offsets)]
    scene+=struct.pack('<11I',*offsets)
    return raw[:20]+struct.pack('<I',len(scene))+scene


def catalog(raw):
    doors=parse_verified_doors(raw)
    pos,dest=boundary_portal_bindings(None,None,doors,stages())
    runtime=SimpleNamespace(revision=1286,doors=doors,portal_positions=pos,
        portal_destinations=dest,scene_names={60000:'北島',58001:'航海圖',11016:'島嶼'})
    with patch('wlre.services.world.runtime_1275.baseline_revision',return_value='1286'), \
         patch('wlre.services.world.catalog_source_policy.official_runtime',return_value=runtime):
        return Portals(),doors,dest


class EventConveyTests(unittest.TestCase):
    def test_eve_only_conditional_exit_reaches_catalog_and_sends_real_door(self):
        c,doors,dest=catalog(fixture())
        row,=c.for_scene(60000)
        self.assertEqual(row['destination'],58001)
        self.assertEqual(row['direct_door_index'],3)  # not Convey 96 or event 7
        self.assertIsNone(destination_problem(row))
        event,=doors[60000][0]['touch_event_records']
        self.assertEqual(event['convey_transfers'][0]['condition']['para_kind'],30381)
        self.assertTrue(event['destination_decoded'])
        self.assertEqual(marked_portals([row],None,allow_unprojected=True),[row])
        s=State();s.player.update(role_id=1,scene=60000,x=100,y=100)
        packet,=PortalTravel(c).start_direct(s,Mock(),row['id'],0)
        self.assertEqual(packet.payload,struct.pack('<H',3))

    def test_all_conditional_destinations_retained_and_server_decides(self):
        c,_,_=catalog(fixture((58001,11016)))
        row,=c.for_scene(60000)
        self.assertIsNone(row['destination'])
        self.assertEqual(row['destination_candidates'],[11016,58001])
        self.assertTrue(row['event_decided_only'])
        self.assertIsNone(destination_problem(row))
        self.assertEqual(marked_portals([row],None,allow_unprojected=True)[0]['index'],3)
        s=State();s.player.update(role_id=1,scene=60000,x=100,y=100)
        service=PortalTravel(c);service.start_direct(s,Mock(),row['id'],0)
        service.observe(dict(type='position_snapshot',role_id=1,scene=11016,x=200,y=300),s,Mock())
        self.assertEqual(s.portal_travel['status'],'completed')

    def test_missing_convey_does_not_guess_destination(self):
        c,doors,dest=catalog(fixture(missing=True))
        self.assertFalse(dest)
        self.assertEqual(doors[60000][0]['touch_event_records'][0]['missing_convey_ids'],[96])
        self.assertFalse(c.for_scene(60000)[0]['direct_eligible'])

    def test_unknown_destination_not_enabled(self):
        _,_,dest=catalog(fixture((65530,)))
        self.assertFalse(dest)

    def test_bad_section_offset_is_rejected(self):
        raw=bytearray(fixture());struct.pack_into('<I',raw,len(raw)-44+6*4,1)
        with self.assertRaises(DoorSourceError):parse_verified_doors(bytes(raw))

    def test_length_prefixed_name_decodes(self):
        raw=fixture();name='往巨鯨島'.encode('cp950')
        raw=raw[:34]+(bytes([len(name)])+name).ljust(20,b'\0')+raw[54:]
        self.assertEqual(parse_verified_doors(raw)[60000][0]['name'],'往巨鯨島')

    def test_event_conflict_cannot_be_resurrected_by_second_runtime_pass(self):
        from wlre.services.world.event_portals import reconcile_event_portals
        doors=parse_verified_doors(fixture())
        positions={(60000,3):{'x':120,'y':4400}}
        targets={(60000,3):{'destination':11016}}
        reconcile_event_portals(doors,stages(),positions,targets)
        reconcile_event_portals(doors,stages(),positions,targets)
        self.assertFalse(targets)
        self.assertEqual(doors[60000][0]['portal_resolution_issue'],'conflicting_event_destination')

    def test_line_boundary_is_kept_without_inventing_width(self):
        from wlre.services.world.event_portals import reconcile_event_portals
        doors=parse_verified_doors(fixture());doors[60000][0].update(bottom=1)
        positions,targets={},{}
        reconcile_event_portals(doors,stages(),positions,targets)
        self.assertEqual(positions[60000,3]['trigger_bounds'],(0,0,280,0))
        self.assertTrue(targets[60000,3]['event_convey_verified'])

    def test_conditional_same_scene_transfer_waits_for_changed_coordinates(self):
        c,_,_=catalog(fixture((60000,58001)))
        row,=c.for_scene(60000)
        state=State();state.player.update(role_id=1,scene=60000,x=100,y=100)
        service=PortalTravel(c);service.start_direct(state,Mock(),row['id'],0)
        service.observe(dict(type='position_snapshot',role_id=1,scene=60000,x=100,y=100),state,Mock())
        self.assertIsNotNone(service.pending)
        service.observe(dict(type='position_snapshot',role_id=1,scene=60000,x=300,y=400),state,Mock())
        self.assertEqual(state.portal_travel['status'],'completed')

    def test_conditional_unexpected_map_is_reported(self):
        c,_,_=catalog(fixture((58001,11016)))
        row,=c.for_scene(60000)
        state=State();state.player.update(role_id=1,scene=60000,x=100,y=100)
        service=PortalTravel(c);service.start_direct(state,Mock(),row['id'],0)
        service.observe(dict(type='position_snapshot',role_id=1,scene=12345,x=300,y=400),state,Mock())
        self.assertEqual(state.portal_travel['status'],'different_map')
