"""Instance-house entry correlation and explicit server-confirmed exit."""
from copy import deepcopy
from types import SimpleNamespace
import struct
import unittest
from unittest.mock import Mock, patch

import test_tent_1262 as fixtures
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.world.tent import command, expire, TIMEOUT, exit_door_index
from wlre.ui.overview_ui import OverviewPanel
from wlre.ui.crafting_browser import CraftingBrowser


class DynamicTentExitTests(unittest.TestCase):
    def setUp(self):
        self.state=fixtures.ready()
        # Use a non-default door index to prove the command follows current data.
        self.runtime=SimpleNamespace(revision=1286,catalog_identity=SimpleNamespace(key='a'*64),
            stages={12170:{},12050:{}},
            doors={10299:[{'index':7,'x':100,'y':200}]},
            portal_destinations={(10299,7):{'matched_stage_map':True,
                'destination_verified':True,'destination':12050,'event_x':100,'event_y':200}})
        self.patch=patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=self.runtime)
        self.patch.start();self.addCleanup(self.patch.stop)

    def position(self,scene=63503,role_id=91):
        return fixtures.observe(self.state,Packet(12,1,struct.pack('<IHHH',role_id,scene,1000,2600)))

    def furniture(self,owner=91):
        return fixtures.observe(self.state,Packet(62,4,struct.pack('<I',owner)))

    def request_entry(self):
        fixtures.observe(self.state,Packet(65,1,fixtures.camp()))
        command(self.state,{'action':'enter'},now=0)

    def enter(self):
        self.request_entry()
        self.furniture()
        self.position()
        self.assertTrue(self.state.tent['inside'])

    def test_scene_63503_confirms_with_entry_and_own_furniture(self):
        self.enter()
        self.assertEqual(self.state.tent['interior_scene'],63503)
        self.assertEqual(self.state.tent['return_scene'],12170)
        self.assertIsNone(self.state.tent['pending'])

    def test_position_before_furniture_confirms_in_either_packet_order(self):
        self.request_entry()
        self.position()
        self.assertFalse(self.state.tent['inside'])
        self.furniture()
        self.assertTrue(self.state.tent['inside'])

    def test_other_players_furniture_or_position_cannot_confirm_entry(self):
        self.request_entry()
        self.furniture(owner=100)
        self.position(role_id=100)
        self.assertFalse(self.state.tent['inside'])
        self.position()
        self.assertFalse(self.state.tent['inside'])

    def test_ordinary_scene_change_is_not_mistaken_for_tent_entry(self):
        self.request_entry()
        self.furniture()
        self.position(scene=12050)
        self.assertFalse(self.state.tent['inside'])

    def test_late_authoritative_entry_can_resolve_a_timeout(self):
        self.request_entry()
        self.furniture()
        self.assertTrue(expire(self.state,TIMEOUT+1))
        self.position()
        self.assertTrue(self.state.tent['inside'])
        self.assertFalse(self.state.tent['uncertain'])

    def test_exit_uses_current_template_trigger_without_requiring_map_image(self):
        self.enter()
        packet,=command(self.state,{'action':'leave'},now=2)
        self.assertEqual(packet,Packet(20,8,Writer().u16(7).build()))
        self.assertEqual(self.state.player['scene'],63503)
        self.assertTrue(self.state.tent['inside'])
        self.assertEqual(self.state.tent['pending']['action'],'leave')
        with self.assertRaises(ProtocolError):
            command(self.state,{'action':'leave'},now=3)
        self.position(role_id=100,scene=12170)
        self.assertIsNotNone(self.state.tent['pending'])
        self.position(scene=12170)
        self.assertFalse(self.state.tent['inside'])
        self.assertIsNone(self.state.tent['pending'])
        self.assertIsNone(self.state.tent['interior_scene'])
        self.assertEqual(self.state.tent['deployed_scene'],12170)

    def test_new_physical_binding_exits_without_old_stage_marker_flag(self):
        self.enter()
        link=self.runtime.portal_destinations[10299,7]
        link.update(matched_stage_map=False,matched_touch_region=True)
        packet,=command(self.state,{'action':'leave'},now=2)
        self.assertEqual(packet,Packet(20,8,Writer().u16(7).build()))
        self.assertTrue(self.state.tent['inside'])
        self.position(scene=12170)
        self.assertFalse(self.state.tent['inside'])

    def test_named_stage_only_exit_uses_current_door_and_waits_for_return_scene(self):
        self.enter()
        self.runtime.doors[10299][0]['touch_event_ids']=[9]
        self.runtime.portal_destinations[10299,7].update(
            index=7,destination=None,destination_verified=False,stage_marker_only=True,
            door_binding_verified=True,stage_marker_kind=3,stage_marker_name_id=10,
            stage_marker_event_id=0)
        self.runtime.texts={10:'離開小屋'}
        packet,=command(self.state,{'action':'leave'},now=2)
        self.assertEqual(packet.payload,Writer().u16(7).build())
        self.assertEqual(self.state.player['scene'],63503)
        self.assertTrue(self.state.tent['inside'])
        self.position(scene=12170)
        self.assertFalse(self.state.tent['inside'])

    def test_stage_only_exit_needs_entry_context_touch_proof_and_valid_marker(self):
        link=self.runtime.portal_destinations[10299,7]
        link.update(index=7,destination=None,destination_verified=False,stage_marker_only=True,
                    door_binding_verified=True,stage_marker_kind=2,stage_marker_name_id=10)
        self.runtime.texts={10:'離開小屋'}
        self.runtime.doors[10299][0]['touch_event_ids']=[9]
        with self.assertRaises(ProtocolError):exit_door_index()
        self.assertEqual(exit_door_index(return_scene=12170),7)
        self.runtime.doors[10299][0]['touch_event_ids']=[]
        with self.assertRaises(ProtocolError):exit_door_index(return_scene=12170)
        self.runtime.doors[10299][0]['touch_event_ids']=[9]
        self.runtime.texts.clear()
        with self.assertRaises(ProtocolError):exit_door_index(return_scene=12170)

    def test_missing_or_conflicting_official_exit_data_does_not_guess_index(self):
        self.enter()
        self.runtime.portal_destinations.clear()
        with self.assertRaises(ProtocolError):
            command(self.state,{'action':'leave'},now=2)
        self.assertIsNone(self.state.tent['pending'])
        self.runtime.doors[10299].append({'index':8,'x':100,'y':200})
        for index in (7,8):
            self.runtime.portal_destinations[(10299,index)]={
                'matched_stage_map':True,'destination_verified':True,
                'destination':12050,'event_x':100,'event_y':200}
        with self.assertRaises(ProtocolError):exit_door_index()

    def test_invalid_current_link_does_not_fall_back_to_legacy_door_one(self):
        self.runtime.portal_destinations[(10299,7)]['event_x']=101
        with self.assertRaises(ProtocolError):exit_door_index()

    def test_floor_link_is_not_selected_as_an_outdoor_exit(self):
        self.runtime.doors[10299].append({'index':8,'x':1,'y':2})
        self.runtime.portal_destinations[(10299,8)]={
            'matched_stage_map':True,'destination_verified':True,
            'destination':10298,'event_x':1,'event_y':2}
        self.assertEqual(exit_door_index(),7)

    def test_exit_requires_confirmed_interior_and_respects_battle(self):
        self.state.player['scene']=63503
        self.furniture()
        with self.assertRaises(ProtocolError):
            command(self.state,{'action':'leave'},now=2)
        self.state=fixtures.ready()
        self.enter()
        self.state.battle['active']=True
        with self.assertRaisesRegex(ProtocolError,'戰鬥'):
            command(self.state,{'action':'leave'},now=2)

    def test_exit_timeout_never_claims_arrival_or_resends(self):
        self.enter()
        command(self.state,{'action':'leave'},now=2)
        self.assertTrue(expire(self.state,2+TIMEOUT))
        self.assertTrue(self.state.tent['inside'])
        self.assertTrue(self.state.tent['uncertain'])
        with self.assertRaises(ProtocolError):
            command(self.state,{'action':'leave'},now=40)
        self.position(scene=12170)
        self.assertFalse(self.state.tent['inside'])
        self.assertFalse(self.state.tent['uncertain'])

    def test_rejection_keeps_interior_and_displays_server_reason(self):
        self.enter()
        command(self.state,{'action':'leave'},now=2)
        self.state.apply({'type':'event_rejected','reason':'伺服器拒絕離開'})
        self.assertTrue(self.state.tent['inside'])
        self.assertIsNone(self.state.tent['pending'])
        self.assertIn('拒絕',self.state.tent['status'])

    def test_overview_and_crafting_callbacks_switch_to_leave(self):
        for inside,action in ((False,'enter'),(True,'leave')):
            app=SimpleNamespace(snapshot={'tent':{'inside':inside}},send=Mock())
            OverviewPanel.enter_or_leave_tent(SimpleNamespace(app=app))
            app.send.assert_called_once_with({'type':'tent','action':action})
            app.send.reset_mock()
            CraftingBrowser.toggle_tent(SimpleNamespace(app=app,state=app.snapshot))
            app.send.assert_called_once_with({'type':'tent','action':action})
