"""Verified 1262 Eve interaction: read-only previews, safe manual reply."""
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.npc_dialogue import choose_npc_option
from wlre.network.wire import Packet, ProtocolError
from wlre.services.world.npc_interact import NPCInteractIndex


SOURCE_MD5='81af690395d5e6a233afa9a664e2c555'


def fake_row(index=1, form_kind=1, *, mixed=False):
    return {'index':index,'form_kind':form_kind,'link_number':1,'items':[
        {'id':1,'text_id':50063,'database_kind':1,'kind':1},
        {'id':2,'text_id':10001,'database_kind':2 if mixed else 1,'kind':3},
        {'id':3,'text_id':10002,'database_kind':1,'kind':3},
        {'id':4,'text_id':50063,'database_kind':1,'kind':4},
    ]}


TALKS={50063:'是否要進入小遊戲呢？',10001:'要。',10002:'不要。'}


class NPCInteractTests(unittest.TestCase):
    def setUp(self):
        self.index=NPCInteractIndex.__new__(NPCInteractIndex)
        self.index.scenes={10000:{1:fake_row(),2:fake_row(2,form_kind=3),
                                  3:fake_row(3,mixed=True)}}

    def test_verified_normal_choices_follow_lua_button_order(self):
        result=self.index.choices(10000,1,TALKS)
        self.assertEqual(result['title'],'是否要進入小遊戲呢？')
        self.assertEqual([(r['choice'],r['text_id'],r['text']) for r in result['options']],
                         [(0,10001,'要。'),(1,10002,'不要。')])
        self.assertIsNone(self.index.choices(10000,2,TALKS))  # No shop.
        self.assertIsNone(self.index.choices(10000,3,TALKS))  # No unverified DB.
        self.assertIsNone(self.index.choices(10001,1,TALKS))
        self.assertIsNone(self.index.choices(10000,1,{10001:'要。'}))

    def test_default_missing_index_disables_npc_options(self):
        with patch('wlre.services.world.npc_interact.RESOURCE_ROOT',
                   Path('/nonexistent-catalogue-location-1262')):
            self.assertIsNone(NPCInteractIndex().choices(10000,1,TALKS))

    def make_state(self,scene=10000,index=1):
        state=State()
        state.player={'scene':scene}
        state.npc_dialogue={'active':True,'scene':scene,'phase':'choice_unavailable',
                            'effect_type':6,'option_index':index}
        state.event_flow={'blocked':True}
        return state

    def attempt(self,state,command):
        with (patch('wlre.services.world.npc_interact.NPCInteractIndex',
                    return_value=self.index),
              patch('wlre.services.world.npc_talk.load_catalog',
                    return_value=TALKS)):
            return choose_npc_option(state,command)

    def test_manual_reply_is_one_shot_and_uses_confirmed_offset(self):
        state=self.make_state()
        cmd={'type':'npc_choose','confirmed':True,'scene':10000,
             'interact_index':1,'choice':1,'text_id':10002}
        self.assertEqual(self.attempt(state,cmd),[Packet(20,9,b'\x1f')])  # 31
        self.assertEqual(state.npc_dialogue['phase'],'awaiting_choice')
        self.assertTrue(state.event_flow['awaiting_response'])
        with self.assertRaises(ProtocolError):self.attempt(state,cmd)

    def test_server_continue_after_choice_remains_manual(self):
        from wlre.network.protocol import decode
        state=self.make_state()
        cmd={'confirmed':True,'scene':10000,'interact_index':1,
             'choice':0,'text_id':10001}
        self.attempt(state,cmd)
        state.apply(decode(Packet(20,10,b'')))
        self.assertEqual(state.npc_dialogue['phase'],'continue')
        self.assertFalse(state.event_flow['awaiting_response'])

    def test_reject_unverified_scene_index_shop_stale_and_unconfirmed(self):
        good={'confirmed':True,'scene':10000,'interact_index':1,
              'choice':0,'text_id':10001}
        variants=[
            {'confirmed':False},{'scene':10001},{'interact_index':2},
            {'interact_index':3},{'choice':10},{'choice':-1},
            {'text_id':10002},{'text_id':True},{'choice':True}
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                state=self.make_state(index=variant.get('interact_index',1))
                with self.assertRaises(ProtocolError):
                    self.attempt(state,{**good,**variant})
                self.assertEqual(state.npc_dialogue['phase'],'choice_unavailable')

    def test_battle_and_scene_change_are_blocked(self):
        cmd={'confirmed':True,'scene':10000,'interact_index':1,
             'choice':0,'text_id':10001}
        state=self.make_state()
        state.battle['active']=True
        with self.assertRaises(ProtocolError):self.attempt(state,cmd)
        state=self.make_state()
        state.player['scene']=10001
        with self.assertRaises(ProtocolError):self.attempt(state,cmd)


# These historical tests verify bundled 1262 fixtures explicitly. Production
# LaLa now defaults to 1275, with no implicit source fallback.
from unittest.mock import patch as _legacy_patch
_legacy_context = None


def setUpModule():
    global _legacy_context
    _legacy_context = _legacy_patch(
        'wlre.services.world.runtime_1275.baseline_revision', return_value='1262')
    _legacy_context.start()
    from wlre.services.world.npc_item_data import item_catalog
    item_catalog.cache_clear()


def tearDownModule():
    from wlre.services.world.npc_item_data import item_catalog
    item_catalog.cache_clear()
    _legacy_context.stop()

