import unittest
from types import SimpleNamespace
from unittest.mock import patch
from wlre.services.world.item_stack_rules import can_overlap,CurrentStackRules


def row(**changes):
    value=dict(fit_type=8,kind=1,special=0,available_time=0,limited_time=0,use_count=0,flags2=0,attributes=[{'kind':0},{'kind':0}])
    value.update(changes);return value


class StackRules(unittest.TestCase):
    def test_every_official_exclusion_and_boundary(self):
        self.assertTrue(can_overlap(50000,row()))
        for sid in (34106,34152,34163,34164,34168,34180):self.assertFalse(can_overlap(sid,row()))
        for fit in range(1,7):self.assertFalse(can_overlap(50000,row(fit_type=fit)))
        for fit in (9,10,11):self.assertFalse(can_overlap(50000,row(fit_type=fit)))
        for kind in (39,58,76):self.assertFalse(can_overlap(50000,row(kind=kind)))
        self.assertFalse(can_overlap(50000,row(fit_type=7,available_time=1)))
        self.assertTrue(can_overlap(50000,row(fit_type=8,available_time=1)))
        for fit in (7,8):
            self.assertFalse(can_overlap(50000,row(fit_type=fit,limited_time=1)))
            self.assertFalse(can_overlap(50000,row(fit_type=fit,flags2=1)))
            self.assertTrue(can_overlap(50000,row(fit_type=fit,flags2=2)))
        for attribute in (25,26):self.assertFalse(can_overlap(50000,row(special=151,attributes=[{'kind':attribute},{'kind':0}])))
        self.assertTrue(can_overlap(50000,row(special=151,attributes=[{'kind':0},{'kind':25}])))
        for sid in (34298,34299):
            self.assertFalse(can_overlap(sid,row(special=151)))
            self.assertTrue(can_overlap(sid,row(special=0)))
        self.assertFalse(can_overlap(50000,row(special=130,use_count=2)))
        self.assertTrue(can_overlap(50000,row(special=130,use_count=1)))
    def test_missing_metadata_is_never_a_stackability_guess(self):
        for changes in ({'attributes':[]},{'fit_type':None},{'flags2':None}):
            with self.assertRaises(ValueError):can_overlap(50000,row(**changes))
    def test_live_facade_switches_version_and_preserves_server_proof(self):
        from wlre.core.inventory_updates import add_item
        rules=CurrentStackRules();runtime=SimpleNamespace(items={50000:{'stackable':True}})
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=runtime),patch('wlre.core.inventory_updates.STACKABLE',rules):
            frozen=rules.snapshot()
            self.assertTrue(rules['50000']);runtime.items[50000]['stackable']=False
            self.assertTrue(frozen['50000'])
            self.assertFalse(rules['50000'])
            inventory={'items':{},'capacity':10,'server_stackable':{'50000':True}}
            self.assertTrue(add_item(inventory,{'item_id':50000,'count':2,'index':1}))
            self.assertEqual(inventory['items']['1']['count'],2)
            runtime.items={}
            self.assertIsNone(rules.get('50000'))
            fresh={'items':{},'capacity':10}
            self.assertFalse(add_item(fresh,{'item_id':50000,'count':2,'index':1}))
            self.assertEqual(fresh['items'],{})
            self.assertTrue(add_item(fresh,{'item_id':50000,'count':1,'index':1}))

    def test_cold_rules_block_speculative_claim_capacity_and_storage(self):
        from wlre.services.expedition.manager import claim_space
        from wlre.services.items.room_storage_transfer import is_stackable
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=None):
            self.assertIsNone(claim_space({'rewards':[{'kind':10,'id':50000,'value':2}],'special_reward':{'kind':0,'id':0,'value':0}}))
            self.assertFalse(is_stackable(50000,item={'count':1}))
            self.assertTrue(is_stackable(50000,item={'count':2}))
