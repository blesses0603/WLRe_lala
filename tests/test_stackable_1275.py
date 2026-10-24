"""Official Lua ItemData.CanOverlap equivalence and 1275-only stack rules."""
import unittest
from copy import deepcopy
from types import SimpleNamespace
from wlre.services.items.stackable_1275 import (
    Stackable1275Error, can_overlap_1275, build_1275_stackables,
    activate_1275_stackables)
from wlre.core.inventory_updates import STACKABLE, add_item


def item(**kw):
    row={'id':10000,'kind':32,'fit_type':8,'special':0,'use_count':0,
         'item_available_time':0,'item_limited_time':0,'flags2':0,
         'attributes':[{'kind':0},{'kind':0}]}
    row.update(kw)
    return row


class Stackable1275Tests(unittest.TestCase):
    def test_literal_itemdata_canoverlap_special_cases(self):
        self.assertTrue(can_overlap_1275(item()))
        for row in (
            item(id=34106), item(id=34152), item(id=34163),
            item(id=34164), item(id=34168), item(id=34180),
            item(fit_type=10), item(fit_type=11), item(fit_type=3),
            item(fit_type=9), item(kind=39), item(kind=58),
            item(kind=76), item(fit_type=8, flags2=1),
            item(fit_type=8, item_limited_time=2),
            item(special=130, use_count=2),
            item(special=151, attributes=[{'kind':25},{'kind':0}]),
            item(special=151, attributes=[{'kind':26},{'kind':0}]),
            item(id=34298, special=151),
        ):
            with self.subTest(row=row):
                self.assertFalse(can_overlap_1275(row))
        # EquipFit=8 (food) ignores itemAvailableTime in official Lua,
        # but seasonal/limited-time flags are still checked.
        self.assertTrue(can_overlap_1275(item(item_available_time=20)))

    def test_invalid_data_fails_closed(self):
        for bad in (None,{},item(attributes=[]),item(flags2=None)):
            with self.subTest(bad=bad), self.assertRaises(Stackable1275Error):
                can_overlap_1275(bad)
        with self.assertRaises(Stackable1275Error):
            build_1275_stackables({'source_revision':1262,'items':{}})
        with self.assertRaises(Stackable1275Error):
            build_1275_stackables({'source_revision':1275,'items':{
                '999':item(id=10000)}})

    def test_in_place_activation_and_backpack_add(self):
        source={'source_revision':1275,'items':{
            '10000':item(id=10000),'10001':item(id=10001,fit_type=9)}}
        saved=dict(STACKABLE)
        original_ref=STACKABLE
        try:
            count=activate_1275_stackables(
                SimpleNamespace(revision=1275,item_catalog=source))
            self.assertEqual(count,2)
            self.assertIs(original_ref,STACKABLE)
            self.assertTrue(STACKABLE['10000'])
            self.assertFalse(STACKABLE['10001'])
            bag={'items':{},'capacity':6,'reliable':True}
            self.assertTrue(add_item(bag,{'item_id':10000,'count':2,'index':1}))
            self.assertEqual(bag['items']['1']['count'],2)
            self.assertTrue(add_item(bag,{'item_id':10001,'count':2,'index':2}))
            self.assertEqual(bag['items']['2']['count'],1)
            self.assertEqual(bag['items']['3']['count'],1)
        finally:
            original_ref.clear()
            original_ref.update(saved)

    def test_failed_activate_leaves_old_mapping(self):
        previous=dict(STACKABLE)
        with self.assertRaises(Stackable1275Error):
            activate_1275_stackables(
                SimpleNamespace(revision=1275,item_catalog={
                    'source_revision':1275,
                    'items':{'10000':item(flags2=None)}}))
        self.assertEqual(STACKABLE,previous)


if __name__=='__main__':
    unittest.main()
