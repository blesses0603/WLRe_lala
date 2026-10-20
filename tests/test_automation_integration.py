"""Cross-service safety under delayed receipts, snapshots and session changes."""
import copy
import queue
import threading
import unittest
from unittest.mock import patch
from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.service_scheduler import advance_services
from wlre.network.wire import ProtocolError
from wlre.services.coordination import command_reason
from wlre.services.items import reservations
from wlre.services.items.combat_resources import available
from wlre.services.expedition import Expedition
from wlre.ui.session_bridge import SessionBridge
from test_expedition import ExpeditionFixture
from test_release import setup as alchemy_setup


class BagRegistry(unittest.TestCase):
    def setUp(self):
        self.state=State();self.state.inventory.update(ready=True,reliable=True,capacity=24,
            items={'1':{'index':1,'item_id':34014,'serial':12,'count':5},
                   '2':{'index':2,'item_id':34014,'serial':13,'count':5}})
    def hold(self,owner='battle',count=2,exclusive=False):
        reservations.acquire(self.state.inventory,owner,[{'index':1,'item_id':34014,'count':count}],exclusive=exclusive)
    def test_duplicate_batch_is_atomic(self):
        original=copy.deepcopy(self.state.inventory)
        with self.assertRaises(ProtocolError):
            reservations.acquire(self.state.inventory,'battle',[{'index':1,'item_id':34014,'count':3}]*2)
        self.assertEqual(self.state.inventory,original)
    def test_foreign_consumer_cannot_take_partially_reserved_stack(self):
        self.hold()
        original=copy.deepcopy(self.state.inventory)
        with self.assertRaises(ProtocolError):self.hold('crafting',1,True)
        self.assertEqual(self.state.inventory,original)
    def test_snapshot_keeps_pending_quantity_and_exclusive_lock(self):
        self.hold('expedition',2,True)
        snapshot=copy.deepcopy(list(self.state.inventory['items'].values()))
        self.state.apply({'type':'bag_snapshot','capacity':24,'items':snapshot})
        self.assertEqual(self.state.inventory['reserved']['1'],2)
        self.assertEqual(available(self.state.inventory,1),0)
        snapshot[0]['count']=3
        self.state.apply({'type':'bag_snapshot','capacity':24,'items':snapshot})
        self.assertEqual(self.state.inventory['reserved']['1'],0)
        self.assertEqual(available(self.state.inventory,1),0)  # still awaits faith confirmation
        reservations.release(self.state.inventory,'expedition')
        self.assertEqual(available(self.state.inventory,1),3)
    def test_replacement_snapshot_invalidates_inventory_and_holds(self):
        self.hold('crafting',2,True)
        values=copy.deepcopy(list(self.state.inventory['items'].values()));values[0]['serial']=99
        self.state.apply({'type':'bag_snapshot','capacity':24,'items':values})
        self.assertFalse(self.state.inventory['reliable'])
        self.assertTrue(self.state.inventory['holds']['crafting'][0]['uncertain'])
        with self.assertRaises(ProtocolError):self.hold('battle')
    def test_unconfirmed_deduction_cannot_release_another_owner(self):
        self.hold('field_supply',1,True)
        reservations.acquire(self.state.inventory,'battle',[{'index':2,'item_id':34014,'count':1}])
        self.state.apply({'type':'bag_delete','index':2,'count':1})
        self.assertNotIn('battle',self.state.inventory['holds'])
        self.assertIn('field_supply',self.state.inventory['holds'])
        self.assertEqual(available(self.state.inventory,1),0)
    def test_rollback_restores_holds_together_with_counters(self):
        saved=reservations.checkpoint(self.state.inventory)
        self.hold()
        reservations.restore(self.state.inventory,saved)
        self.assertFalse(self.state.inventory['holds'])
        self.assertEqual(available(self.state.inventory,1),5)


class Ownership(unittest.TestCase):
    def test_service_cannot_change_another_domain_even_nested(self):
        state=State()
        with state.editing('expedition'):
            state.expedition['status']='test'
            for write in (lambda:setattr(state,'auto_battle',{}),lambda:state.knowledge['player']['stats'].update(hp=999),
                          lambda:state.roles.append({'index':1})):
                with self.assertRaises(RuntimeError):write()
        self.assertFalse(state.auto_battle['enabled'])
        self.assertEqual(state.knowledge['player']['stats'],{})
    def test_background_mutation_rejected_but_snapshot_is_detached(self):
        state=State();state.inventory['items']={'1':{'item_id':34014,'count':5}}
        errors=[]
        def work():
            for mutate in (lambda:state.inventory['items']['1'].update(count=0),lambda:state.roles.append({}),
                           lambda:setattr(state,'phase','world_ready')):
                try:mutate()
                except RuntimeError as exc:errors.append(str(exc))
        thread=threading.Thread(target=work);thread.start();thread.join()
        self.assertEqual(len(errors),3)
        snapshot=state.snapshot();snapshot['inventory']['items']['1']['count']=0
        self.assertEqual(state.inventory['items']['1']['count'],5)
    def test_nested_service_scope_restores_original_owner_on_error(self):
        state=State();logic=SessionLogic()
        with state.editing('expedition'):
            logic.auto_battle.start(state,{})
            with self.assertRaises(RuntimeError):state.auto_battle['enabled']=False
        self.assertTrue(state.auto_battle['enabled'])


class Coordinate:
    def mapping(self,scene):return None
    def to_navigation(self,scene,x,y):return x,y
    def to_packet(self,scene,x,y):return x,y

class Movement:
    def __init__(self):self.converter=Coordinate();self.active=False
    def stop(self,state,reason=''):self.active=False
    def start(self,state,x,y,now):self.active=True
    def observe(self,event,state):pass
    def tick(self,state,now):return []


class ParallelAutomation(ExpeditionFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.state.player={'role_id':1,'scene':60000}
        self.state.location.update(confirmed={'scene':60000,'x':500,'y':500,'packet_number':1},confirmed_is_current=True)
        self.logic=SessionLogic();self.logic.world_acknowledged=True
        self.logic.expedition=self.service;self.logic.movement=Movement()
    def scheduler(self,now):
        sent=[]
        with patch('wlre.network.service_scheduler.time.monotonic',return_value=now):
            advance_services(self.logic,self.state,sent.append,sent.append,lambda event:None,None)
        return sent
    def test_three_services_pause_for_real_battle_and_resume_independently(self):
        self.logic.command({'type':'start_auto_battle'},self.state)
        self.logic.command({'type':'start_roaming'},self.state)
        self.logic.command({'type':'start_expedition','settings':self.settings},self.state)
        self.state.battle['active']=True
        self.logic.roaming.observe({'type':'battle_start'},self.state,self.logic.movement)
        self.assertEqual(self.scheduler(10),[])
        self.assertEqual(self.state.roaming['status'],'paused_battle')
        self.state.battle['active']=False
        event={'type':'event_end'};self.state.apply(event);self.logic.receive(event,self.state)
        sent=self.scheduler(13)
        self.assertIn((31,15),[(p.main,p.sub) for p in sent])
        self.assertGreater(self.state.roaming['goals_started'],0)
        self.logic.command({'type':'stop_auto_battle'},self.state)
        self.assertTrue(self.state.roaming['enabled']);self.assertTrue(self.state.expedition['enabled'])
    def test_stop_during_faith_request_keeps_hold_until_both_replies(self):
        self.state.expedition['roles']['1']['faith']=70
        self.state.inventory.update(ready=True,reliable=True,capacity=24,items={'3':{'index':3,'item_id':34014,'count':5,'serial':12}})
        self.service.start(self.state,self.settings);self.service.tick(self.state,10)
        self.service.stop(self.state)
        self.event({'type':'bag_delete','index':3,'count':2})
        self.assertEqual(available(self.state.inventory,3),0)
        self.assertTrue(self.state.inventory['holds']['expedition'])
        self.event({'type':'outpost_faith','index':1,'faith':80,'show':0})
        self.assertEqual(available(self.state.inventory,3),3)
        self.assertFalse(self.state.expedition['enabled'])
        self.assertEqual(self.service.tick(self.state,100),[])
    def test_disconnect_freezes_pending_request_and_reconnect_starts_disabled(self):
        self.state.expedition['roles']['1']['faith']=70
        self.state.inventory.update(ready=True,reliable=True,items={'3':{'index':3,'item_id':34014,'count':5,'serial':12}})
        self.service.start(self.state,self.settings);self.service.tick(self.state,10)
        self.logic.disconnect(self.state)
        self.assertFalse(self.state.inventory['reliable'])
        self.assertTrue(self.state.inventory['holds']['expedition'][0]['uncertain'])
        with self.assertRaises(ProtocolError):self.service.start(self.state,self.settings)
        fresh=State();new=SessionLogic()
        self.assertFalse(fresh.expedition['enabled']);self.assertFalse(fresh.auto_battle['enabled'])
        self.assertFalse(fresh.roaming['enabled']);self.assertIsNone(new.expedition.pending)
        self.assertFalse(fresh.inventory.get('holds'))
    def test_late_reply_after_timeout_does_not_resume_automation(self):
        self.service.start(self.state,self.settings);self.service.tick(self.state,10)
        self.service.tick(self.state,31)
        self.event({'type':'expedition_team','team':{'index':1,'quest':2,'members':[101,0,0,0],'minutes':360}})
        self.assertEqual(self.service.tick(self.state,100),[])
        self.assertTrue(self.state.expedition['uncertain'])
    def test_local_craft_pause_is_available_during_pending_maintenance(self):
        self.state.maintenance['uncertain']=True
        self.state.crafting['auto_continue']=True
        self.assertEqual(self.logic.command({'type':'craft','action':'plan_pause'},self.state),[])
        self.assertFalse(self.state.crafting['auto_continue'])


class SessionIsolation(unittest.TestCase):
    def test_old_session_callbacks_cannot_publish_into_new_session(self):
        old=queue.Queue();current=queue.Queue();old_bridge=SessionBridge(old);new_bridge=SessionBridge(current)
        old_bridge.snapshot({'player':{'role_id':1}});old_bridge.finished()
        new_bridge.snapshot({'player':{'role_id':2}})
        self.assertEqual(current.get_nowait(),('state',{'player':{'role_id':2}}))
        self.assertTrue(current.empty());self.assertEqual(old.qsize(),2)
    def test_alchemy_timeout_keeps_registry_and_will_not_retry(self):
        state,command=alchemy_setup();logic=SessionLogic()
        logic.alchemy.start(state,command,0)
        logic.alchemy.tick(state,16)
        self.assertTrue(state.inventory['holds']['alchemy'])
        self.assertTrue(all(row['uncertain'] for row in state.inventory['holds']['alchemy']))
        self.assertFalse(state.inventory['reliable'])
        state.apply({'type':'bag_snapshot','capacity':200,'items':copy.deepcopy(list(state.inventory['items'].values()))})
        self.assertFalse(state.inventory['reliable'])
        self.assertEqual(logic.alchemy.tick(state,100),[])
        self.assertFalse(state.alchemy['enabled'])


class CraftingIntegration(unittest.TestCase):
    def setUp(self):
        from wlre.services.items.crafting import RECIPES,confirmed_unlocked
        self.recipe=next(r for r in RECIPES.values() if confirmed_unlocked(r) and r['materials'] and r['tool_id'])
        self.state=State(phase='world_ready');self.state.player={'role_id':1}
        self.state.crafting['ready']=True
        self.state.furniture.update(ready=True,owner=1,items={'1':{'index':1,'item_id':self.recipe['tool_id'],'status':0}})
        items={}
        for i,mat in enumerate(self.recipe['materials'],1):
            items[str(i)]={'index':i,'item_id':mat['item_id'],'serial':i+100,'count':mat['count']+2}
        self.state.inventory.update(ready=True,reliable=True,capacity=200,items=items)
        self.logic=SessionLogic();self.logic.world_acknowledged=True
        self.command={'type':'craft','action':'add','item_id':self.recipe['item_id'],'count':1}
    def add(self):
        with patch('wlre.services.items.crafting.time.monotonic',return_value=0):
            packets=self.logic.command(self.command,self.state)
        self.assertEqual((packets[0].main,packets[0].sub),(64,1))
    def event(self,value):self.state.apply(value);self.logic.receive(value,self.state)
    def ack(self):
        self.event({'type':'craft_added','row':{'index':1,'item_id':self.recipe['item_id'],'count':1,'elapsed':0,'base_time':self.recipe['seconds']}})
    def test_add_locks_ingredients_until_ack_and_all_deductions(self):
        self.add();allocations=copy.deepcopy(self.logic.crafting.pending['allocations'])
        self.assertTrue(self.state.inventory['holds']['crafting'])
        # Enabling AI is just intent outside combat; held craft ingredients
        # remain reserved until their authoritative deductions arrive.
        self.assertEqual(self.logic.command({'type':'start_auto_battle'},self.state),[])
        self.assertTrue(self.state.auto_battle['enabled'])
        self.assertTrue(self.state.inventory['holds']['crafting'])
        self.ack();self.assertIsNotNone(self.logic.crafting.pending)
        for row in allocations:self.event({'type':'bag_delete','index':row['index'],'count':row['count']})
        self.assertIsNone(self.logic.crafting.pending)
        self.assertNotIn('crafting',self.state.inventory['holds'])
        self.logic.command({'type':'start_auto_battle'},self.state)
        self.assertTrue(self.state.auto_battle['enabled'])
    def test_disconnect_does_not_release_crafting_ingredients(self):
        self.add();self.logic.disconnect(self.state)
        self.assertTrue(self.state.inventory['holds']['crafting'])
        self.assertTrue(all(row['uncertain'] for row in self.state.inventory['holds']['crafting']))
        self.assertFalse(self.state.inventory['reliable'])
    def test_replaced_ingredient_is_not_accepted_as_consumed(self):
        self.add();self.ack()
        values=copy.deepcopy(list(self.state.inventory['items'].values()));values[0]['serial']=999
        self.event({'type':'bag_snapshot','items':values,'capacity':200})
        self.assertIsNotNone(self.logic.crafting.pending)
        self.logic.crafting.tick(self.state,16)
        self.assertTrue(self.state.crafting['uncertain'])
        self.assertTrue(self.state.inventory['holds']['crafting'])
