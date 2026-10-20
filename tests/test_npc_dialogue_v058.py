"""1262 manual NPC: strict index, one-shot continuation and safe S20 parsing."""
import struct
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.npc_dialogue import decode_effect, request_npc, advance_npc
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.world.npc_catalog import NPCIndex


def s20_effect(effect_type=1, mean_number=211):
    return Packet(20, 1, struct.pack('<BHBBBHB IHBH'.replace(' ', ''),
                                   0, 101, 1, effect_type, 3, 2, 0,
                                   0, mean_number, 0, 70))


class NPCDialogueTests(unittest.TestCase):
    def test_s20_fields_and_truncated_payload(self):
        event = decode(s20_effect())
        self.assertEqual(event['type'], 'event_active')
        self.assertEqual(event['npc_effect']['mean_number'], 211)
        self.assertEqual(event['npc_effect']['effect_type'], 1)
        self.assertEqual(event['npc_effect']['event_no'], 70)
        self.assertEqual(decode_effect(s20_effect().payload+b'\xaa')['extension_bytes'], 1)
        for size in range(18):
            self.assertIsNone(decode(Packet(20,1,b'\x00'*size))['npc_effect'])

    def test_ordinary_server_effect_does_not_take_over_manual_session(self):
        state=State()
        state.apply(decode(s20_effect()))
        self.assertFalse(state.npc_dialogue['active'])
        self.assertEqual(state.npc_dialogue['last_effect']['effect_type'], 1)

    def test_manual_talk_one_step_choice_denied_and_end(self):
        state=State()
        state.player={'scene':100}
        state.npc_dialogue={'active':True,'phase':'requesting','scene':100}
        state.apply(decode(s20_effect()))
        self.assertEqual(state.npc_dialogue['phase'],'talk')
        self.assertEqual(state.npc_dialogue['text_id'],211)
        self.assertEqual(advance_npc(state),[Packet(20,6,b'\x00')])
        with self.assertRaises(ProtocolError):advance_npc(state)
        state.apply(decode(s20_effect(6,7)))
        self.assertEqual(state.npc_dialogue['phase'],'choice_unavailable')
        self.assertEqual(state.npc_dialogue['option_index'],7)
        with self.assertRaises(ProtocolError):advance_npc(state)
        state.apply(decode(Packet(20,8)))
        self.assertEqual(state.npc_dialogue['phase'],'ended')
        self.assertFalse(state.event_flow['blocked'])

    def test_initial_server_continuation_is_manual_only(self):
        state=State()
        state.npc_dialogue={'active':True,'phase':'requesting','scene':100}
        state.apply(decode(Packet(20,10,b'')))
        self.assertEqual(state.npc_dialogue['phase'],'continue')
        self.assertTrue(state.event_flow['blocked'])

    def test_server_out_of_range_unblocks(self):
        state=State()
        state.npc_dialogue={'active':True,'phase':'requesting','scene':100}
        state.event_flow={**state.event_flow,'blocked':True}
        state.apply(decode(Packet(20,74,b'\x01')))
        self.assertEqual(state.npc_dialogue['phase'],'rejected')
        self.assertFalse(state.event_flow['blocked'])


class NPCStartTests(unittest.TestCase):
    def setUp(self):
        idx=NPCIndex()
        self.scene,self.npc=next((int(scene),entry) for scene,entries in idx.scenes.items()
                                 for entry in entries if entry['event_count']>0)
        self.state=State()
        self.state.phase='world_ready'
        self.state.player={'scene':self.scene,'role_id':1234}
        self.state.location={'confirmed_is_current':True,
                              'confirmed':{'scene':self.scene,'x':1,'y':1}}
        self.command={'confirmed':True,'scene':self.scene,
            'npc_index':self.npc['index'],'npc_id':self.npc['npc_id'],
            'x':self.npc['x'],'y':self.npc['y']}

    def test_single_verified_index_sent_once(self):
        with patch('wlre.services.battle.party.own_team',return_value=None):
            self.assertEqual(request_npc(self.state,self.command),
                             [Packet(20,1,struct.pack('<H',self.npc['index']))])
        with self.assertRaises(ProtocolError):
            request_npc(self.state,self.command)

    def test_wrong_scene_identity_coordinate_and_confirmation_denied(self):
        for altered in ({'scene':self.scene+1},{'npc_id':self.npc['npc_id']+1},
                        {'x':self.npc['x']+1},{'confirmed':False}):
            with self.subTest(altered=altered):
                with self.assertRaises(ProtocolError):
                    request_npc(self.state,{**self.command,**altered})
        self.state.event_flow['blocked']=True
        with self.assertRaises(ProtocolError):
            request_npc(self.state,self.command)
