import copy
import struct
import unittest
from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.battle.auto_battle import defaults
from wlre.services.items.combat_resources import CAT, available
from wlre.services.items.maintenance import cleanup_action, cleanup_packet


def item(sid,count=1,serial=1,damage=0):
    return {'item_id':sid,'count':count,'serial':serial,'serial_version':1,'damage':damage}


class MaintenanceFlow(unittest.TestCase):
    def setUp(self):
        self.state=State(phase='world_ready');self.state.player={'role_id':1}
        self.state.battle_count=1;self.state.battle={'active':False,'post_event':{'status':'completed'}}
        self.state.inventory.update(ready=True,reliable=True,items={})
        self.logic=SessionLogic();self.logic.world_acknowledged=True
        self.settings=defaults();self.settings['field_heal']=False
        self.settings['maintenance'].update(repair_enabled=True,cleanup_enabled=True,repair_items=[34104,0],
                                            cleanup_items=[32001]+[0]*14)
        self.logic.auto_battle.start(self.state,self.settings)
        self.guard=self.logic.maintenance
        self.state.knowledge['player']['equips']=[item(22001,serial=10,damage=220)]
        self.state.inventory['items']['1']=item(34104,serial=20)
        self.state.inventory['items']['2']=item(32001,3,serial=30)

    def tick(self,t):return self.guard.tick(self.state,self.logic,t)

    def begin(self):
        self.tick(0);return self.tick(1)

    def event(self,packet):
        event=decode(packet);self.state.apply(event);self.logic.receive(event,self.state);return event

    def damage(self,grid,index,damage,npc=0):
        return Packet(23,140,struct.pack('<BBBIB',1,grid,index,damage,npc))

    def test_repair_waits_for_both_tool_wear_and_equipment_restored(self):
        packets=self.begin();self.assertEqual(len(packets),1)
        self.assertEqual((packets[0].main,packets[0].sub),(23,84))
        self.assertEqual(packets[0].payload,struct.pack('<BHBBBHHH',2,22001,1,0,1,1,34104,1))
        self.assertEqual(available(self.state.inventory,'1'),0)
        self.event(self.damage(2,1,0));self.tick(2)
        self.assertIsNotNone(self.guard.pending)
        self.event(self.damage(1,1,25));self.tick(3)
        self.assertIsNone(self.guard.pending)
        self.assertEqual(self.state.maintenance['completed'],1)
        self.assertEqual(available(self.state.inventory,'1'),1)
        self.tick(4);packets=self.tick(5)
        self.assertEqual((packets[0].main,packets[0].sub),(27,3))
        self.assertEqual(packets[0].payload,b'\x02\x03')

    def test_reverse_update_order_and_active_partner_repair(self):
        self.state.knowledge['player']['equips']=[]
        self.state.knowledge.update(active_npc_id=101,companions={'1':{'index':1,'npc_id':101,
            'equips':[item(22001,serial=10,damage=220)]}})
        packet=self.begin()[0]
        self.assertEqual(packet.payload[4],1)
        self.event(self.damage(1,1,10));self.tick(2)
        self.assertIsNotNone(self.guard.pending)
        self.event(self.damage(3,1,0,1));self.tick(3)
        self.assertIsNone(self.guard.pending)

    def test_sale_reply_is_authoritative_deduction_not_double_deletion(self):
        self.state.knowledge['player']['equips']=[]
        packet=self.begin()[0];self.assertEqual((packet.main,packet.sub),(27,3))
        self.event(Packet(27,6,struct.pack('<IBB',100,2,3)));self.tick(2)
        self.assertNotIn('2',self.state.inventory['items'])
        self.assertTrue(self.state.inventory['reliable']);self.assertIsNone(self.guard.pending)
        self.assertEqual(self.state.maintenance['completed'],1)

    def test_restrictions_choose_drop_only_if_not_saleable(self):
        sid=next(int(sid) for sid,data in CAT['items'].items() if data['restrict']&16 and not data['restrict']&128)
        forbidden=next(int(sid) for sid,data in CAT['items'].items() if data['restrict']&16 and data['restrict']&128)
        self.assertEqual(cleanup_action(sid),'delete');self.assertIsNone(cleanup_action(forbidden))
        self.state.knowledge['player']['equips']=[]
        self.logic.auto_battle.settings['maintenance']['cleanup_items']=[sid]+[0]*14
        self.state.inventory['items']={'2':item(sid,2,serial=30)}
        packet=self.begin()[0]
        self.assertEqual((packet.main,packet.sub,packet.payload),(23,124,b'\x02\x02\x02'))
        self.event(Packet(23,9,b'\x02\x02\x00'));self.tick(2)
        self.assertIsNone(self.guard.pending)

    def test_sale_failure_never_falls_back_to_discard(self):
        self.state.knowledge['player']['equips']=[];self.begin()
        self.event(Packet(27,8,b'\x00'));self.assertEqual(self.tick(2),[])
        self.assertTrue(self.guard.uncertain);self.assertFalse(self.logic.auto_battle.enabled)
        self.assertIn('2',self.state.inventory['items'])
        self.assertEqual(self.tick(100),[])

    def test_timeout_holds_slots_and_blocks_restart_until_relogin(self):
        self.begin();self.assertEqual(self.tick(22),[])
        self.assertTrue(self.guard.uncertain);self.assertFalse(self.logic.auto_battle.enabled)
        self.assertEqual(available(self.state.inventory,'1'),0)
        with self.assertRaises(ProtocolError):self.logic.command({'type':'start_auto_battle','settings':self.settings},self.state)
        self.assertEqual(self.tick(100),[])

    def test_other_operations_and_roaming_wait_for_confirmation(self):
        self.begin()
        for command in ({'type':'start_alchemy'},{'type':'craft'},{'type':'start_expedition'},
                        {'type':'field_item'},{'type':'start_roaming'},{'type':'companion'}):
            with self.subTest(command=command),self.assertRaises(ProtocolError):self.logic.command(command,self.state)
        self.assertEqual(self.logic.auto_battle.tick(self.state,self.logic,2),[])
        self.assertEqual(self.state.auto_battle['status'],'maintenance')
        self.logic.command({'type':'stop_auto_battle'},self.state)
        self.event(self.damage(2,1,0));self.event(self.damage(1,1,25));self.tick(3)
        self.assertIsNone(self.guard.pending)
        self.assertEqual(self.tick(4),[])

    def test_snapshot_preserves_hold_and_slot_replacement_stops_automation(self):
        self.begin()
        self.state.apply({'type':'bag_snapshot','capacity':50,'items':[item(34104,serial=21)|{'index':1}]})
        self.assertEqual(self.state.inventory['maintenance_slots'],['1'])
        self.assertEqual(available(self.state.inventory,'1'),0)
        self.tick(2);self.assertTrue(self.guard.uncertain)

    def test_checking_pauses_roaming_and_missing_repair_items_keep_it_waiting(self):
        self.tick(0)
        self.assertTrue(self.state.maintenance['checking'])
        self.logic.roaming.enabled=True;self.logic.roaming.role_id=1;self.logic.roaming.scene=None
        self.logic.roaming.tick(self.state,self.logic.movement,.1)
        self.assertEqual(self.state.roaming['status'],'paused_event')
        self.state.inventory['items'].clear()
        self.tick(1)
        self.assertTrue(self.state.maintenance['checking'])
        self.assertIsNone(self.guard.pending)
        self.assertIn('不足',self.state.maintenance['status'])
        self.logic.auto_battle.stop(self.state)
        self.tick(2)
        self.assertFalse(self.state.maintenance['checking'])

    def test_repair_ack_for_wrong_equipment_does_not_confirm(self):
        self.begin();self.event(self.damage(1,1,25))
        self.event(self.damage(3,1,0,2));self.tick(2)
        self.assertIsNotNone(self.guard.pending)
        self.state.knowledge['player']['equips'][0]['serial']=999
        self.tick(3);self.assertTrue(self.guard.uncertain)

    def test_sell_count_mismatch_stops_without_second_packet(self):
        self.state.knowledge['player']['equips']=[];self.begin()
        self.event(Packet(27,6,struct.pack('<IBB',100,2,2)))
        self.assertEqual(self.tick(2),[]);self.assertTrue(self.guard.uncertain)
        self.assertEqual(self.state.inventory['items']['2']['count'],1)

    def test_no_action_in_battle_events_or_before_first_battle(self):
        for change in ('battle','event','first','craft','supply','expedition'):
            with self.subTest(change=change):
                self.setUp()
                if change=='battle':self.state.battle['active']=True
                elif change=='event':self.state.event_flow['blocked']=True
                elif change=='first':self.state.battle_count=0
                elif change=='craft':self.state.crafting['pending']={'foo':1}
                elif change=='supply':self.state.inventory['field_supply']={'pending':True}
                else:self.state.expedition['pending']={'foo':1}
                self.assertEqual(self.begin(),[])

    def test_locked_reserved_and_timed_items_are_never_acted_on(self):
        self.state.knowledge['player']['equips']=[]
        original=copy.deepcopy(self.state.inventory)
        for change in ('locked','reserved','timed','expedition','alchemy'):
            inv=copy.deepcopy(original)
            if change=='locked':inv['items']['2']['locked']=True
            elif change=='reserved':inv['reserved']['2']=1
            elif change=='timed':inv['items']['2']['limited_time']=1
            elif change=='expedition':inv['expedition_slots']=['2']
            else:inv['alchemy_slots']=['2']
            self.state.inventory=inv
            self.assertEqual(self.begin(),[])
        for bad in (0,256,True):
            with self.assertRaises(ProtocolError):cleanup_packet('sell',2,bad)

    def test_configured_repair_and_recovery_items_are_not_sold(self):
        self.state.knowledge['player']['equips']=[]
        self.logic.auto_battle.settings['field_heal']=True
        self.logic.auto_battle.settings['recovery']['hp']['items']=[32001]+[0]*9
        self.logic.auto_battle.settings['maintenance']['cleanup_items']=[34104,32001]+[0]*13
        self.assertEqual(self.begin(),[])


class MaintenanceProtocol(unittest.TestCase):
    def test_sacred_object_fit_type_11_maps_to_equipment_slot_7(self):
        sid=next(int(sid) for sid,data in CAT['items'].items() if data['fit_type']==11)
        state=State();state.apply({'type':'player_equip_data','equips':[item(sid,damage=220)]})
        self.assertEqual(state.knowledge['player']['equips'][6]['item_id'],sid)
        state.apply(decode(Packet(23,35,struct.pack('<BH',0,sid))))
        self.assertEqual(state.knowledge['player']['equips'][6]['damage'],250)

    def test_damage_layouts_and_truncation(self):
        samples=[Packet(23,27,b'\x01\xdc'),Packet(23,28,b'\x02\x01\xdc'),
                 Packet(23,140,b'\x04\x01\x00\x02'),Packet(23,35,struct.pack('<BH',0,22001)),
                 Packet(23,140,struct.pack('<BBBBH',2,2,1,0,22001)),Packet(27,6,struct.pack('<IBB',10,2,3))]
        for packet in samples:
            self.assertNotEqual(decode(packet)['type'],'unimplemented')
            for length in range(len(packet.payload)):
                with self.subTest(main=packet.main,sub=packet.sub,length=length),self.assertRaises(ProtocolError):
                    decode(Packet(packet.main,packet.sub,packet.payload[:length]))
