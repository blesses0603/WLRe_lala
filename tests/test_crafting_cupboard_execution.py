"""Room.CheckSmithMaterial order and C64-1 cupboard execution/confirmation."""
from copy import deepcopy
from itertools import permutations
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.items import reservations
from wlre.services.items.crafting import Crafting, RECIPES, recipe_plan
from wlre.services.items.crafting_browser_model import availability, material_rows

SID=34144
PRODUCT=34026


def recipe(**kw):
    return {'item_id':PRODUCT,'tool_id':39001,'output':1,'seconds':10,
            'materials':[{'item_id':SID,'count':4}],'design_id':0,'time_id':0,
            'limit_kind':0,'open_used':0,**kw}


def ready():
    state=State(phase='world_ready',initial_data_complete=True)
    state.player={'role_id':1,'scene':12170}
    state.inventory.update(ready=True,reliable=True,capacity=24,
        items={'3':{'index':3,'item_id':SID,'count':2,'serial':123}})
    state.furniture.update(ready=True,owner=1,
        items={'7':{'index':7,'item_id':39001,'status':0}})
    state.crafting['ready']=True
    state.apply(decode(Packet(62,57,Writer().u8(1).u8(1).u16(1).u16(300).u16(SID).u16(1000).build())))
    return state


class CupboardCraftingExecutionTests(unittest.TestCase):
    def setUp(self):
        self.state=ready();self.service=Crafting()
        self.enterContext(patch.dict(RECIPES,{str(PRODUCT):recipe()},clear=True))
        self.enterContext(patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=None))

    def event(self,event):
        self.state.apply(event);self.service.observe(event,self.state,1)

    def test_legacy_packet_uses_bag_first_and_u16_cupboard_index_and_amount(self):
        _,allocations,packet=recipe_plan(self.state,PRODUCT,2)
        expected=Writer().u16(7).u16(PRODUCT).u8(2).u8(1).u8(3).u8(2).u16(1).u16(300).u16(6).u8(0).build()
        self.assertEqual(packet,Packet(64,1,expected))
        self.assertEqual([(a.get('source','bag'),a['count']) for a in allocations],[('bag',2),('materials',6)])

    def test_current_recipe_id_format_uses_same_cupboard_tail(self):
        row=recipe(recipe_id=99)
        runtime=SimpleNamespace(recipe_catalog=[row])
        with patch.dict(RECIPES,{str(PRODUCT):row}),patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=runtime):
            _,_,packet=recipe_plan(self.state,PRODUCT,2)
        expected=Writer().u16(7).u16(99).u16(PRODUCT).u8(2).u8(1).u8(3).u8(2).u16(1).u16(300).u16(6).u8(0).build()
        self.assertEqual(packet,Packet(64,1,expected))

    def test_cupboard_only_recipe_has_zero_bag_materials(self):
        self.state.inventory['items']={}
        _,allocations,packet=recipe_plan(self.state,PRODUCT,1)
        self.assertEqual(len(allocations),1)
        self.assertEqual(allocations[0]['source'],'materials')
        self.assertEqual(packet.payload,Writer().u16(7).u16(PRODUCT).u8(1).u8(0).u16(1).u16(300).u16(4).u8(0).build())

    def test_cupboard_count_above_255_is_not_truncated(self):
        with patch.dict(RECIPES,{str(PRODUCT):recipe(materials=[{'item_id':SID,'count':250}])}):
            _,_,packet=recipe_plan(self.state,PRODUCT,3)
        self.assertEqual(packet.payload[-7:],Writer().u16(1).u16(300).u16(748).u8(0).build())

    def test_multiple_cupboard_slots_for_same_material_are_allocated_exactly(self):
        self.state.room_storage['materials']['items']['300']['count']=3
        self.state.room_storage['materials']['items']['301']={'index':301,'item_id':SID,'count':100}
        _,allocations,_=recipe_plan(self.state,PRODUCT,2)
        self.assertEqual([(a['index'],a['count']) for a in allocations],[(3,2),(300,3),(301,3)])

    def test_ack_and_both_material_deductions_confirm_in_every_order(self):
        for order in permutations(range(3)):
            with self.subTest(order=order):
                self.state=ready();self.service=Crafting()
                self.service.command(self.state,{'action':'add','item_id':PRODUCT,'count':2},0)
                events=[{'type':'craft_added','row':{'index':1,'item_id':PRODUCT,'count':2,'base_time':20,'elapsed':0}},
                        {'type':'bag_delete','index':3,'count':2},
                        decode(Packet(62,57,Writer().u8(2).u16(300).u16(6).build()))]
                for i in order[:2]:self.event(events[i])
                self.assertIsNotNone(self.service.pending)
                self.event(events[order[2]])
                self.assertIsNone(self.service.pending)
                self.assertEqual(self.state.room_storage['materials']['items']['300']['count'],994)
                self.assertEqual(reservations.available(self.state.room_storage['materials'],300),994)

    def test_pending_cupboard_materials_cannot_be_allocated_again(self):
        self.service.command(self.state,{'action':'add','item_id':PRODUCT,'count':2},0)
        self.assertEqual(reservations.available(self.state.room_storage['materials'],300),0)
        with self.assertRaises(ProtocolError):recipe_plan(self.state,PRODUCT,2)

    def test_reservations_are_atomic_if_second_container_reservation_fails(self):
        acquire=reservations.acquire
        saved_bag=reservations.checkpoint(self.state.inventory)
        def fail_second(bucket,owner,allocations,**kw):
            if bucket is self.state.room_storage['materials']:raise ProtocolError('changed')
            return acquire(bucket,owner,allocations,**kw)
        with patch.object(reservations,'acquire',side_effect=fail_second),self.assertRaises(ProtocolError):
            self.service.command(self.state,{'action':'add','item_id':PRODUCT,'count':2},0)
        self.assertEqual(reservations.checkpoint(self.state.inventory),saved_bag)
        self.assertEqual(self.state.room_storage['materials']['holds'],{})
        self.assertIsNone(self.service.pending)

    def test_timeout_keeps_cupboard_hold_and_blocks_later_storage_moves(self):
        self.service.command(self.state,{'action':'add','item_id':PRODUCT,'count':2},0)
        self.assertEqual(self.service.tick(self.state,16),[])
        self.assertTrue(self.state.crafting['uncertain'])
        self.assertTrue(self.state.room_storage['uncertain'])
        self.assertTrue(self.state.room_storage['materials']['holds']['crafting'][0]['uncertain'])
        self.assertEqual(self.service.tick(self.state,20),[])

    def test_custom_plan_submits_cupboard_materials_through_same_service(self):
        self.service.command(self.state,{'action':'plan_set','rows':[{'item_id':PRODUCT,'count':2}],'revision':0},0)
        self.service.command(self.state,{'action':'plan_start','revision':1},0)
        packet,=self.service.tick(self.state,1)
        self.assertEqual(packet.payload[-7:],Writer().u16(1).u16(300).u16(6).u8(0).build())
        self.assertTrue(self.service.pending['material_allocations'])

    def test_ui_availability_uses_combined_materials_and_does_not_double_count(self):
        self.assertEqual(availability(self.state.snapshot(),recipe(),2)[0],'可製作')
        self.service.command(self.state,{'action':'add','item_id':PRODUCT,'count':2},0)
        row=material_rows(self.state.snapshot(),recipe(),2)[0]
        self.assertEqual(row['usable'],0)
        self.assertEqual(row['cupboard'],0)

    def test_unsynced_or_unreliable_cupboard_does_not_supply_recipe(self):
        for change in ({'ready':False},{'reliable':False}):
            self.state=ready();self.state.room_storage['materials'].update(change)
            with self.subTest(change=change),self.assertRaises(ProtocolError):recipe_plan(self.state,PRODUCT,2)

    def test_transfer_pending_does_not_allow_a_simultaneous_recipe(self):
        self.state.room_storage['pending']='withdraw'
        with self.assertRaisesRegex(ProtocolError,'存取'):recipe_plan(self.state,PRODUCT,2)


if __name__=='__main__':unittest.main()
