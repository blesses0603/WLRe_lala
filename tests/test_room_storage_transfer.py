"""UIRoomStorage.lua C62 byte layouts and server-confirmed two-container moves."""
from copy import deepcopy
from itertools import permutations
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.service_scheduler import advance_services
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.items import reservations
from wlre.services.items.room_storage_transfer import RoomStorageTransfer, plan_transfer
from wlre.ui.resource_view import ResourceView

SID=34144


def ready():
    state=State(phase='world_ready',initial_data_complete=True)
    state.player={'role_id':1,'scene':12170}
    state.inventory.update(ready=True,reliable=True,capacity=24,
        items={'3':{'index':3,'item_id':SID,'count':20,'serial':123,'serial_version':1}})
    state.apply(decode(Packet(62,72,Writer().u8(200).u16(500).u16(10000).build())))
    state.apply({'type':'storage_garage_initial','items':[
        {'index':5,'item_id':SID,'count':10,'serial':123,'serial_version':1}]})
    state.apply(decode(Packet(62,57,Writer().u8(1).u8(1).u16(1).u16(300).u16(SID).u16(1000).build())))
    return state


def command(target='materials',action='withdraw',count=4):
    return {'type':'room_storage','target':target,'action':action,
            'index':3 if action=='deposit' else 300 if target=='materials' else 5,
            'item_id':SID,'count':count}


class StorageTransferTests(unittest.TestCase):
    def setUp(self):self.state=ready();self.service=RoomStorageTransfer()

    def event(self,event):
        self.state.apply(event);self.service.observe(event,self.state)

    def events(self,target,action,count=4):
        ack=decode(Packet(62,71,bytes([1 if action=='deposit' else 2])))
        bag_add={'type':'bag_add','item':{'index':3,'item_id':SID,'count':count,'serial':123,'serial_version':1}}
        bag_del={'type':'bag_delete','index':3,'count':count}
        if target=='garage':
            add={'type':'storage_garage_add','item':{'index':5,'item_id':SID,'count':count,'serial':123,'serial_version':1}}
            remove={'type':'storage_garage_delete','index':5,'count':count}
        else:
            add=decode(Packet(62,57,Writer().u8(1).u8(2).u16(300).u16(SID).u16(count).build()))
            remove=decode(Packet(62,57,Writer().u8(2).u16(300).u16(count).build()))
        return (ack,bag_del,add) if action=='deposit' else (ack,remove,bag_add)

    def test_four_manual_wire_layouts_match_lua(self):
        for target,action,sub,payload in (
            ('garage','deposit',18,bytes([1,3,4])),
            ('garage','withdraw',19,bytes([1,5,4])),
            ('materials','deposit',52,bytes([1,1,3,4])),
            ('materials','withdraw',52,Writer().u8(2).u8(1).u16(300).u8(4).build())):
            with self.subTest(target=target,action=action):
                packet,_=plan_transfer(self.state,command(target,action))
                self.assertEqual(packet,Packet(62,sub,payload))

    def test_all_reply_orders_wait_for_result_and_both_container_updates(self):
        for target in ('garage','materials'):
            for action in ('deposit','withdraw'):
                for order in permutations(range(3)):
                    with self.subTest(target=target,action=action,order=order):
                        self.state=ready();self.service=RoomStorageTransfer()
                        events=self.events(target,action)
                        self.service.command(self.state,command(target,action),0)
                        self.assertEqual(self.state.inventory['items']['3']['count'],20)
                        for i in order[:2]:self.event(events[i])
                        self.assertIsNotNone(self.service.pending)
                        self.event(events[order[2]])
                        self.assertIsNone(self.service.pending)
                        self.assertIsNone(self.state.room_storage['pending'])
                        self.assertFalse(self.state.room_storage['uncertain'])
                        self.assertEqual(self.state.inventory['items']['3']['count'],16 if action=='deposit' else 24)

    def test_large_cupboard_withdraw_splits_u16_index_and_u8_counts(self):
        packet,=self.service.command(self.state,command(count=401),0)
        expected=Writer().u8(2).u8(3).u16(300).u8(200).u16(300).u8(200).u16(300).u8(1).build()
        self.assertEqual(packet,Packet(62,52,expected))
        self.event(decode(Packet(62,57,Writer().u8(2).u16(300).u16(401).build())))
        for index,count in ((4,200),(5,200),(6,1)):
            self.event({'type':'bag_add','item':{'index':index,'item_id':SID,'count':count,'serial':123,'serial_version':1}})
        self.assertIsNotNone(self.service.pending)
        self.event(decode(Packet(62,71,b'\x02')))
        self.assertIsNone(self.service.pending)
        self.assertEqual(self.state.room_storage['materials']['items']['300']['count'],599)

    def test_duplicate_and_foreign_bag_consumers_are_blocked(self):
        self.service.command(self.state,command(action='deposit'),0)
        with self.assertRaises(ProtocolError):self.service.command(self.state,command(),1)
        logic=SessionLogic();logic.world_acknowledged=True
        with self.assertRaisesRegex(ProtocolError,'存取'):
            logic.command({'type':'craft','action':'add','item_id':7,'count':1},self.state)
        self.assertEqual(reservations.available(self.state.inventory,3),0)

    def test_material_slot_holds_are_separate_from_same_numbered_bag_slots(self):
        self.state.room_storage['materials']['items']['3']=self.state.room_storage['materials']['items'].pop('300')
        self.state.room_storage['materials']['items']['3']['index']=3
        self.service.command(self.state,{**command(),'index':3},0)
        self.assertEqual(reservations.available(self.state.inventory,3),20)
        self.assertEqual(reservations.available(self.state.room_storage['materials'],3),0)

    def test_timeout_never_releases_uncertain_hold_or_retries(self):
        self.service.command(self.state,command(action='deposit'),0)
        self.assertEqual(self.service.tick(self.state,16),[])
        self.assertTrue(self.state.room_storage['uncertain'])
        self.assertFalse(self.state.inventory['reliable'])
        self.assertEqual(self.service.tick(self.state,20),[])
        with self.assertRaises(ProtocolError):self.service.command(self.state,command(),21)
        self.assertTrue(self.state.inventory['holds']['storage'][0]['uncertain'])

    def test_definitive_error_without_deductions_releases_hold(self):
        self.service.command(self.state,command(action='deposit'),0)
        self.event(decode(Packet(62,25,b'\x01\x0b')))
        self.assertIsNone(self.service.pending)
        self.assertFalse(self.state.room_storage['uncertain'])
        self.assertEqual(reservations.available(self.state.inventory,3),20)
        self.assertIn('拒絕',self.state.room_storage['status'])

    def test_error_after_partial_deduction_is_uncertain(self):
        self.service.command(self.state,command(action='deposit'),0)
        self.event({'type':'bag_delete','index':3,'count':2})
        self.event(decode(Packet(62,25,b'\x01\x0b')))
        self.assertTrue(self.state.room_storage['uncertain'])
        self.assertIsNotNone(self.service.pending)

    def test_wrong_receipt_or_unrelated_item_never_confirms(self):
        self.service.command(self.state,command(),0)
        self.event(decode(Packet(62,71,b'\x01')))
        self.event({'type':'bag_add','item':{'index':4,'item_id':34026,'count':4}})
        self.assertIsNotNone(self.service.pending)

    def test_stale_revision_identity_and_quantity_are_rejected(self):
        for change in ({'storage_revision':-1},{'bag_revision':-1},{'item_id':34026},
                       {'count':1001},{'count':True},{'index':True}):
            with self.subTest(change=change),self.assertRaises(ProtocolError):
                plan_transfer(self.state,{**command(),**change})
        self.assertIsNone(self.state.room_storage['pending'])

    def test_storage_and_bag_capacity_are_checked_before_send(self):
        self.state.inventory['capacity']=1
        with self.assertRaises(ProtocolError):plan_transfer(self.state,command(count=401))
        self.state=ready();self.state.room_storage['materials']['capacity']=1
        self.state.room_storage['material_stack_limit']=1000
        with self.assertRaises(ProtocolError):plan_transfer(self.state,command(action='deposit'))

    def test_locked_expiring_and_enhanced_materials_are_not_sent(self):
        for change in ({'locked':True},{'limited_time':1},{'available_time':1},{'enhance_level':1}):
            state=ready();state.inventory['items']['3'].update(change)
            with self.subTest(change=change),self.assertRaises(ProtocolError):
                plan_transfer(state,command(action='deposit'))

    def test_unsynced_storage_does_not_enable_actions(self):
        self.state.room_storage['materials']['ready']=False
        with self.assertRaises(ProtocolError):plan_transfer(self.state,command())

    def test_scheduler_expires_storage_without_a_ui_timer(self):
        logic=SessionLogic();logic.world_acknowledged=True
        with patch('wlre.services.items.room_storage_transfer.time.monotonic',return_value=0):
            logic.command(command(),self.state)
        with patch('wlre.network.service_scheduler.time.monotonic',return_value=16):
            advance_services(logic,self.state,Mock(),Mock(),Mock(),None)
        self.assertTrue(self.state.room_storage['uncertain'])

    def test_disconnect_preserves_uncertainty(self):
        self.service.command(self.state,command(),0)
        self.service.disconnect(self.state)
        self.assertTrue(self.state.room_storage['uncertain'])

    def test_cupboard_proof_handles_new_item_bag_deltas_without_changing_global_metadata(self):
        from wlre.core.inventory_updates import STACKABLE
        sid=65001
        self.assertNotIn(str(sid),STACKABLE)
        self.state.apply(decode(Packet(62,57,Writer().u8(1).u8(2).u16(301).u16(sid).u16(100).build())))
        self.state.apply({'type':'bag_add','item':{'index':4,'item_id':sid,'count':50}})
        self.assertTrue(self.state.inventory['reliable'])
        self.assertEqual(self.state.inventory['items']['4']['count'],50)
        self.assertNotIn(str(sid),STACKABLE)

    def test_ui_selection_sends_real_command_after_quantity_and_confirmation(self):
        app=SimpleNamespace(snapshot=self.state.snapshot(),live_active=True,send=Mock())
        page=SimpleNamespace(app=app,window=None)
        grid=SimpleNamespace(selection=lambda:('bag300',),bag_map={'bag300':self.state.snapshot()['room_storage']['materials']['items']['300']})
        with patch('wlre.ui.resource_view.simpledialog.askinteger',return_value=4), \
             patch('wlre.ui.resource_view.messagebox.askyesno',return_value=True):
            ResourceView.transfer_item(page,grid,'materials','withdraw')
        sent=app.send.call_args.args[0]
        self.assertEqual((sent['type'],sent['target'],sent['action'],sent['index'],sent['count']),
                         ('room_storage','materials','withdraw',300,4))
        self.assertIn('storage_revision',sent)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop or Xvfb')
class StorageTransferWindowTests(unittest.TestCase):
    def test_real_resource_window_exposes_and_locks_transfer_buttons(self):
        import tkinter as tk
        root=tk.Tk();self.addCleanup(root.destroy)
        app=SimpleNamespace(root=root,snapshot=ready().snapshot(),live_active=True,send=Mock())
        view=ResourceView(app)
        root.update()
        labels=[button.cget('text') for button,_ in view.storage_buttons]
        self.assertEqual(labels,['存入儲藏室','存入雜物櫃','取出到背包','取出到背包'])
        view.remote_materials.selection_set('bag300')
        with patch('wlre.ui.resource_view.simpledialog.askinteger',return_value=4), \
             patch('wlre.ui.resource_view.messagebox.askyesno',return_value=True):
            view.storage_buttons[-1][0].invoke()
        self.assertEqual(app.send.call_args.args[0]['action'],'withdraw')
        app.snapshot['room_storage'].update(uncertain=True,revision=100)
        view.set_state(app.snapshot);root.update()
        self.assertTrue(all(str(button.cget('state'))=='disabled' for button,_ in view.storage_buttons))


if __name__=='__main__':unittest.main()
