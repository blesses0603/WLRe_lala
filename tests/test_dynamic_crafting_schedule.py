"""Current Smith layout through real crafting commands, receipts and UI eligibility."""
from copy import deepcopy
from types import SimpleNamespace
import struct
import unittest
from unittest.mock import Mock, patch

import test_dynamic_bundle_runtime as fixtures
from wlre.core.state import State
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.world import dynamic_bundle_runtime as dynamic
from wlre.services.items import crafting
from wlre.services.items.crafting_browser_model import availability, owned_counts, material_rows, tool_status
from wlre.services.items.crafting_plan import validate_rows
from wlre.ui.crafting.recipe_detail import render_recipe_detail


class Var:
    def __init__(self,value=''):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class DynamicCraftingScheduleTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.DynamicBundleRuntimeTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        raw=bytearray(self.fixture.raw['SmithData_C'])
        struct.pack_into('<H',raw,6+5,39001)
        struct.pack_into('<HB',raw,6+8,3874,2)
        raw[6+23]=1
        self.fixture.raw['SmithData_C']=bytes(raw)
        self.runtime=dynamic.activate_for_official(self.fixture.remote,**self.fixture.kwargs())
        self.state=State(phase='world_ready')
        self.state.player={'role_id':1}
        self.state.furniture.update(ready=True,owner=1,current_owner=1,
            items={'7':{'index':7,'item_id':39001,'status':0}})
        self.state.inventory.update(ready=True,reliable=True,capacity=24,
            items={'3':{'index':3,'item_id':3874,'count':20,'serial':123}})
        self.state.crafting.update(ready=True)
        self.service=crafting.Crafting()

    def row_packet(self,sub=16,recipe_id=99):
        row=Writer().u8(1).u16(recipe_id).u32(0).u8(2).u32(10).build()
        return Packet(64,sub,row+(b'\x00' if sub==1 else b''))

    def observe(self,event,now):
        with patch('wlre.services.items.crafting.time.monotonic',return_value=now):
            self.state.apply(event)
            self.service.observe(event,self.state,now)

    def test_current_unconditional_recipe_is_schedulable(self):
        row=crafting.RECIPES['3874']
        self.assertFalse(row.get('read_only',False))
        self.assertTrue(crafting.confirmed_unlocked(row))
        self.assertEqual(availability(self.state.snapshot(),row,2)[0],'可製作')
        self.assertEqual(validate_rows([{'item_id':3874,'count':2}]),[{'item_id':3874,'count':2}])
        _,allocations,packet=crafting.recipe_plan(self.state,3874,2)
        self.assertEqual(allocations[0]['count'],4)
        expected=Writer().u16(7).u16(99).u16(3874).u8(2).u8(1).u8(3).u8(4).u16(0).u8(0).build()
        self.assertEqual(packet,Packet(64,1,expected))
        self.assertFalse(self.runtime.can_send_packets)

    def test_production_decoder_resolves_recipe_id_to_product_for_snapshot_and_add(self):
        from wlre.network.protocol import decode
        for sub in (1,16):
            event=decode(self.row_packet(sub))
            row=event['rows'][0] if sub==1 else event['row']
            self.assertEqual((row['recipe_id'],row['item_id']),(99,3874))

    def test_unknown_recipe_id_never_becomes_an_item_id(self):
        with self.assertRaises(ProtocolError):
            crafting.decode_crafting(self.row_packet(recipe_id=3874))

    def test_add_waits_for_queue_and_consumption_then_starts_and_completes(self):
        packet,=self.service.command(self.state,{'action':'add','item_id':3874,'count':2},0)
        self.assertEqual((packet.main,packet.sub),(64,1))
        self.assertEqual(self.state.crafting['queue'],{})
        self.observe(crafting.decode_crafting(self.row_packet()),1)
        self.assertIsNotNone(self.service.pending)
        self.observe({'type':'bag_delete','index':3,'count':4},2)
        self.assertIsNone(self.service.pending)
        self.assertEqual(self.state.crafting['queue']['1']['item_id'],3874)
        packet,=self.service.command(self.state,{'action':'start'},3)
        self.assertEqual(packet,Packet(64,2,Writer().u16(7).u8(1).u8(0).u32(0).build()))
        self.observe({'type':'craft_started','index':1},4)
        self.assertIsNone(self.service.pending)
        complete,=self.service.tick(self.state,15)
        self.assertEqual(complete,Packet(64,10))
        self.assertEqual(self.state.crafting['completed'],0)
        self.observe({'type':'craft_completed','index':1},16)
        self.assertEqual(self.state.crafting['completed'],1)
        self.assertIsNotNone(self.service.wait_output)

    def test_custom_plan_uses_current_recipe_packet(self):
        self.service.command(self.state,{'action':'plan_set','rows':[{'item_id':3874,'count':2}],'revision':0},0)
        self.service.command(self.state,{'action':'plan_start','revision':1},0)
        packet,=self.service.tick(self.state,1)
        self.assertEqual(packet.payload[:6],Writer().u16(7).u16(99).u16(3874).build())
        self.assertEqual(self.service.pending['plan_count'],2)
        self.assertEqual(self.state.crafting['local_plan']['rows'][0]['count'],2)

    def test_missing_equipment_materials_and_sync_are_still_explained(self):
        for field,update,message in (
            ('furniture',{'ready':False},'帳篷'),
            ('furniture',{'items':{}},'設備'),
            ('inventory',{'items':{}},'材料不足'),
            ('crafting',{'ready':False},'尚未同步')):
            state=deepcopy(self.state)
            getattr(state,field).update(update)
            with self.subTest(field=field,update=update):
                with self.assertRaisesRegex(ProtocolError,message):
                    crafting.recipe_plan(state,3874,2)

    def test_timed_design_and_unopened_recipes_remain_blocked(self):
        for change in ({'time_id':1078,'read_only':True},{'design_id':1},{'limit_kind':1},{'open_used':1}):
            row={**crafting.RECIPES['3874'],**change}
            with self.subTest(change=change),patch.dict(crafting.RECIPES,{'3874':row}):
                with self.assertRaises(ProtocolError):crafting.recipe_plan(self.state,3874,1)
                with self.assertRaises(ProtocolError):validate_rows([{'item_id':3874,'count':1}])

    def test_dynamic_33_byte_layout_keeps_legacy_wire_shape(self):
        self.fixture.raw['SmithData_C']=struct.pack('<i',1)+self.fixture.raw['SmithData_C'][6:]
        runtime=dynamic.activate_for_official(self.fixture.remote,**self.fixture.kwargs())
        self.assertNotIn('recipe_id',runtime.recipe_catalog[0])
        _,_,packet=crafting.recipe_plan(self.state,3874,2)
        expected=Writer().u16(7).u16(3874).u8(2).u8(1).u8(3).u8(4).u16(0).u8(0).build()
        self.assertEqual(packet,Packet(64,1,expected))
        row=Writer().u8(1).u16(3874).u32(0).u8(2).u32(10).build()
        self.assertEqual(crafting.decode_crafting(Packet(64,16,row))['row']['item_id'],3874)

    def test_invalidated_runtime_does_not_fall_back_to_old_add_format(self):
        with patch.object(dynamic,'_active',None):
            with self.assertRaisesRegex(ProtocolError,'來源尚未就緒'):
                crafting.recipe_plan(self.state,3874,1)

    def test_timeout_stops_without_resubmitting_materials(self):
        self.service.command(self.state,{'action':'add','item_id':3874,'count':2},0)
        self.assertEqual(self.service.tick(self.state,16),[])
        self.assertTrue(self.state.crafting['uncertain'])
        self.assertFalse(self.state.inventory['reliable'])
        self.assertEqual(self.service.tick(self.state,17),[])

    def detail(self):
        page=SimpleNamespace(selected=3874,state=self.state.snapshot(),app=SimpleNamespace(live_active=True),
            count=Var('2'),detail_key=None,icons=SimpleNamespace(get=lambda *args:''),
            large_image=Mock(),add_button=Mock(),material_widgets=[],material_table=None,
            embedded=True)
        for name in ('name','hold','device','time','reason','message'):setattr(page,name,Var())
        render_recipe_detail(page,recipes=crafting.RECIPES,owned_counts=owned_counts,
            material_rows=material_rows,availability=availability,item_name=lambda i:str(i),
            tool_status=tool_status,effective_time=crafting.effective_time,
            duration=lambda s:str(s),icon_map={},recipe_plan=crafting.recipe_plan)
        return page

    def test_recipe_detail_enables_add_with_current_catalog_and_ready_state(self):
        self.assertEqual(self.detail().add_button.configure.call_args.kwargs,{'state':'normal'})

    def test_recipe_detail_disables_add_with_reason_when_queue_is_not_synced(self):
        self.state.crafting['ready']=False
        page=self.detail()
        self.assertEqual(page.add_button.configure.call_args.kwargs,{'state':'disabled'})
        self.assertIn('排程尚未同步',page.reason.get())
