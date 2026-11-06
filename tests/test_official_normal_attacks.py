import hashlib
import struct
import unittest
from unittest.mock import patch
from wlre.services.world import normal_attack_catalog as catalog
from wlre.services.battle.combat import normal_skill
from wlre.services.battle.battle_commands import catch_allowed
from wlre.network.wire import ProtocolError


def npc_bytes(*ids,catch_byte=0,kind=1,body=2,attack=2):
    result=struct.pack('<I',len(ids))
    for ident in ids:
        fields=bytearray(203)
        struct.pack_into('<H',fields,1,ident)
        fields[26]=catch_byte;fields[27]=body;fields[106]=kind;fields[114]=attack
        # Both names are length-prefixed UTF-16 strings, independent of fields.
        name='測試'.encode('utf-16le')
        result+=struct.pack('<H',len(name))+name+struct.pack('<H',0)+fields
    return result


class OfficialNormalAttacks(unittest.TestCase):
    def parse(self,raw):
        with patch.object(catalog,'NPC_SHA256',hashlib.sha256(raw).hexdigest()):
            return catalog.parse_npcs(raw)

    def test_reviewed_fields_and_fail_closed(self):
        raw=npc_bytes(9)
        self.assertEqual(self.parse(raw),{'9':{'kind':1,'bodyType':2,'normalAttackKind':2,'canCatch':True}})
        self.assertFalse(self.parse(npc_bytes(9,catch_byte=1))['9']['canCatch'])
        with self.assertRaises(ValueError):catalog.parse_npcs(raw)
        for bad in (raw[:-1],raw+b'x',npc_bytes(9,9),npc_bytes(0)):
            with self.subTest(size=len(bad)),self.assertRaises((ValueError,EOFError)):
                self.parse(bad)

    def test_cold_start_and_live_version_change(self):
        actor={'pid':1,'equips':[{'item_id':0} for _ in range(6)]}
        with patch.object(catalog,'_source',return_value=None):
            self.assertEqual(normal_skill(actor,1),10001)
            actor['equips'][2]['item_id']=10
            with self.assertRaises(ProtocolError):normal_skill(actor,1)
        data={'items':{'10':4},'npcs':{},'catch_nets':{}}
        with patch.object(catalog,'_source',return_value=data):
            self.assertEqual(normal_skill(actor,1),10019)
        data['items']['10']=11
        with patch.object(catalog,'_source',return_value=data):
            self.assertEqual(normal_skill(actor,1),10007)

    def test_monster_and_capture_use_one_snapshot(self):
        data={'items':{'10':5},'npcs':{'9':{'kind':1,'normalAttackKind':2,'canCatch':True}},'catch_nets':{'20':10}}
        equips=[{'item_id':0} for _ in range(6)]
        equips[2]['item_id']=10;equips[5]['item_id']=20
        actor={'pid':9,'master_id':1,'equips':equips,'level':1}
        with patch.object(catalog,'_source',side_effect=[data]) as source:
            self.assertEqual(normal_skill(actor,1),10029)
            self.assertEqual(source.call_count,1)
        master={'pid':1,'col':3,'row':1,'level':20,'degree':1,'equips':equips}
        state={'player':{'role_id':1},'battle_units':{'3:1':master}}
        target={'pid':9,'level':135}
        with patch.object(catalog,'_source',return_value=data):
            self.assertTrue(catch_allowed(state,master,target))
            target['level']=136
            self.assertFalse(catch_allowed(state,master,target))
        with patch.object(catalog,'_source',return_value=None):
            self.assertFalse(catch_allowed(state,master,target))

    def test_capture_bonus_uses_first_value_without_guessing_attribute_kind(self):
        raw=npc_bytes(9)
        items={10:{'kind':7,'special':140,'attributes':[{'kind':250,'value':110}]},
               11:{'kind':4,'special':0,'attributes':[{'kind':250,'value':999}]}}
        with patch.object(catalog,'NPC_SHA256',hashlib.sha256(raw).hexdigest()), \
             patch('wlre.services.world.itemdata_v1.ITEMDATA_1296_SHA256',hashlib.sha256(b'items').hexdigest()), \
             patch.object(catalog,'parse_itemdata',return_value=items):
            result=catalog.build_catalog(raw,b'items')
        self.assertEqual(result['catch_nets'],{'10':10})
        self.assertEqual(result['items'],{'10':7,'11':4})
        with self.assertRaises(ValueError):catalog.build_catalog(raw,b'future-format')
