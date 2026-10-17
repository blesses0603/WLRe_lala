import unittest,sys,copy,json,zipfile,io
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wlre.core.state import State
from wlre.services.items.alchemy import AutoAlchemy, material_problem
from wlre.services.items.combat_resources import CAT, apply_live, food_command, field_context
from wlre.network.client import SessionLogic
from wlre.services.battle import auto_battle
from wlre.network.wire import ProtocolError
from PIL import Image
B=Path(__file__).resolve().parents[1]/'wlre/resources'

def setup():
 s=State();s.player={'role_id':111,'name':'測試','scene':12000,'x':0,'y':0};s.inventory.update(ready=True,reliable=True,capacity=200)
 from wlre.services.items.alchemy import category
 mats=[]
 for sid in CAT['items']:
  item={'item_id':int(sid),'count':50,'serial':100+len(mats),'index':1+len(mats)}
  if not material_problem(item) and category(item)=='normal':mats.append(item)
  if len(mats)==2:break
 for row in mats:s.inventory['items'][str(row['index'])]=row
 cmd={'type':'start_alchemy','runs':3,'materials':[{'index':r['index'],'count':1,'item_id':r['item_id']} for r in mats]}
 s.knowledge['player']['stats']={'hp':100,'max_hp':100,'sp':100,'max_sp':100}
 return s,cmd

def complete(a,s):
 p=copy.deepcopy(a.pending)
 for row in p['consumption']:
  event={'type':'bag_delete','index':row['index'],'count':row['count']};apply_live(s,event);a.observe(event,s)
 a.observe({'type':'alchemy_result','item_id':10000,'count':1},s)
 event={'type':'bag_add','source':3,'item':{'index':0,'item_id':10000,'count':1,'serial':999}}
 apply_live(s,event);a.observe(event,s)

class Concurrency(unittest.TestCase):
 def test_can_run_with_ai_roam_and_movement(self):
  s,c=setup();s.auto_battle['enabled']=s.roaming['enabled']=True;s.local_movement={'status':'running'};a=AutoAlchemy()
  self.assertEqual(len(a.start(s,c,0)),1);self.assertTrue(s.auto_battle['enabled']);self.assertTrue(s.roaming['enabled'])
 def test_ai_command_while_pending(self):
  s,c=setup();l=SessionLogic();l.world_acknowledged=True;l.alchemy.start(s,c,0)
  self.assertEqual(l.command({'type':'start_auto_battle'},s),[]);self.assertTrue(s.auto_battle['enabled'])
 def test_start_during_battle_queues(self):
  s,c=setup();s.battle['active']=True;a=AutoAlchemy();self.assertEqual(a.start(s,c,0),[]);self.assertTrue(s.alchemy['paused'])
  s.battle['active']=False;self.assertEqual(len(a.tick(s,1)),1)
 def test_battle_and_postevent_pause_then_resume(self):
  s,c=setup();a=AutoAlchemy();a.start(s,c,0);complete(a,s);self.assertEqual(s.alchemy['completed'],1)
  s.battle.update(active=True);s.battle_count=1;a.observe({'type':'battle_start'},s);self.assertEqual(a.tick(s,1),[])
  s.battle.update(active=False,post_event={'status':'waiting'});self.assertEqual(a.tick(s,2),[])
  s.battle['post_event']['status']='completed';s.event_flow['blocked']=True;self.assertEqual(a.tick(s,3),[])
  s.event_flow['blocked']=False;self.assertEqual(len(a.tick(s,4)),1);self.assertEqual(s.alchemy['completed'],1)
 def test_no_timeout_or_resend_in_battle(self):
  s,c=setup();a=AutoAlchemy();a.start(s,c,0);s.battle['active']=True
  self.assertEqual(a.tick(s,100),[]);self.assertTrue(s.inventory['reliable']);self.assertIsNotNone(a.pending)
  s.battle['active']=False;self.assertEqual(a.tick(s,110),[]);self.assertEqual(a.pending['deadline'],125)
  self.assertEqual(a.tick(s,124),[]);self.assertTrue(s.alchemy['enabled'])
 def test_pending_can_complete_in_battle(self):
  s,c=setup();a=AutoAlchemy();a.start(s,c,0);s.battle['active']=True;a.tick(s,100);complete(a,s)
  self.assertIsNone(a.pending);self.assertTrue(s.alchemy['enabled']);self.assertEqual(a.tick(s,110),[])
 def test_user_stop_does_not_resume(self):
  s,c=setup();a=AutoAlchemy();s.battle['active']=True;a.start(s,c,0);a.stop(s);s.battle['active']=False
  self.assertEqual(a.tick(s,1),[]);self.assertFalse(s.alchemy['enabled'])
 def test_map_change_stops(self):
  s,c=setup();a=AutoAlchemy();a.start(s,c,0);complete(a,s);s.player['scene']=1
  self.assertEqual(a.tick(s,1),[]);self.assertFalse(s.alchemy['enabled'])
 def test_role_change_stops(self):
  s,c=setup();a=AutoAlchemy();a.start(s,c,0);complete(a,s);s.player['role_id']=2
  self.assertEqual(a.tick(s,1),[]);self.assertFalse(s.alchemy['enabled'])
 def test_claims_survive_snapshot(self):
  s,c=setup();a=AutoAlchemy();a.start(s,c,0);claims=list(s.inventory['alchemy_slots'])
  apply_live(s,{'type':'bag_snapshot','capacity':200,'items':list(s.inventory['items'].values())});self.assertEqual(s.inventory['alchemy_slots'],claims)
  complete(a,s);self.assertEqual(s.inventory['alchemy_slots'],[])
 def test_manual_supply_waits_only_pending(self):
  s,c=setup();l=SessionLogic();l.world_acknowledged=True;l.alchemy.start(s,c,0)
  with self.assertRaisesRegex(ProtocolError,'本次煉金'):l.command({'type':'field_item'},s)
  complete(l.alchemy,s);s.knowledge['player']['stats']['hp']=1
  with self.assertRaisesRegex(ProtocolError,'沒有可用'):l.command({'type':'field_item','resource':'hp'},s)
 def test_reserved_slots_queue_not_stop(self):
  s,c=setup();s.inventory['reserved']['199']=1;a=AutoAlchemy();self.assertEqual(a.start(s,c,0),[]);self.assertTrue(s.alchemy['enabled'])
  s.inventory['reserved']['199']=0;self.assertEqual(len(a.tick(s,1)),1)
 def test_field_supply_pending_queues(self):
  s,c=setup();s.inventory['field_supply']={'pending':True};a=AutoAlchemy();self.assertEqual(a.start(s,c,0),[])
  s.inventory['field_supply']['pending']=False;self.assertEqual(len(a.tick(s,1)),1)
 def test_field_supply_uncertain_stops(self):
  s,c=setup();s.inventory['field_supply']={'uncertain':True};a=AutoAlchemy();self.assertEqual(a.start(s,c,0),[]);self.assertFalse(s.alchemy['enabled'])
 def test_food_cannot_take_claimed_slot(self):
  from wlre.services.items.combat_resources import heal_effects
  s,c=setup();sid=next(int(sid) for sid in CAT['items'] if heal_effects(int(sid)).get('hp'))
  s.inventory['items']={'3':{'index':3,'item_id':sid,'count':10}};s.inventory['alchemy_slots']=['3'];s.knowledge['player']['stats']['hp']=1
  ctx,actor=field_context(s.snapshot())
  with self.assertRaisesRegex(ProtocolError,'沒有可用'):food_command(ctx,actor,field=True)
 def test_ai_waits_pending_when_healing_needed(self):
  s,c=setup();l=SessionLogic();l.alchemy.start(s,c,0);s.knowledge['player']['stats']['hp']=1
  l.auto_battle.start(s,{'field_heal':True});self.assertEqual(l.auto_battle.heal_field(s,l,1),[]);self.assertEqual(s.auto_battle['status'],'waiting_heal')
 def test_healthy_ai_does_not_block_movement(self):
  s,c=setup();l=SessionLogic();l.alchemy.start(s,c,0);l.auto_battle.start(s,{'field_heal':True})
  self.assertIsNone(l.auto_battle.heal_field(s,l,1))
 def test_missing_food_does_not_deadlock_alchemy(self):
  s,c=setup();l=SessionLogic();l.alchemy.start(s,c,0);complete(l.alchemy,s);s.knowledge['player']['stats']['hp']=1
  l.auto_battle.start(s,{'field_heal':True});l.auto_battle.heal_field(s,l,1);self.assertEqual(len(l.alchemy.tick(s,1)),1)
 def test_no_optimistic_completion(self):
  s,c=setup();a=AutoAlchemy();a.start(s,c,0);a.observe({'type':'alchemy_result','item_id':10000,'count':1},s)
  self.assertTrue(s.alchemy['pending']);self.assertEqual(s.alchemy['completed'],0)
 def test_timeout_requires_resync(self):
  s,c=setup();a=AutoAlchemy();a.start(s,c,0);a.tick(s,16);self.assertFalse(s.inventory['reliable']);self.assertFalse(s.alchemy['enabled'])
 def test_skill_material_allocation_excludes_alchemy(self):
  from wlre.services.items.combat_resources import allocate
  s,c=setup();a=AutoAlchemy();a.start(s,c,0);sid=c['materials'][0]['item_id']
  with self.assertRaises(ProtocolError):allocate(s.inventory,sid,1)
  s.inventory['items']['10']={'index':10,'item_id':sid,'count':5}
  self.assertEqual(allocate(s.inventory,sid,1)[0]['index'],10)
 def test_manual_reservation_rejects_claimed_material(self):
  from wlre.services.items.combat_resources import reserve
  s,c=setup();a=AutoAlchemy();a.start(s,c,0)
  with self.assertRaisesRegex(ProtocolError,'煉金材料'):reserve(s,[{'index':1,'count':1}])
 def test_same_map_movement_keeps_plan(self):
  s,c=setup();a=AutoAlchemy();a.start(s,c,0);complete(a,s)
  a.observe({'type':'position_snapshot','role_id':111,'scene':12000},s);s.player['x']=100
  self.assertEqual(len(a.tick(s,1)),1)
 def test_default_attack_both(self):
  for p in auto_battle.defaults()['profiles'].values():self.assertEqual([r['id'] for r in p['orderAction']],[10001,0])
 def test_explicit_search_setting_preserved(self):
  cfg=auto_battle.defaults();cfg['profiles']['player']['orderAction'][0]['id']=-1
  self.assertEqual(auto_battle.validate(cfg)['profiles']['player']['orderAction'][0]['id'],-1)

class Images(unittest.TestCase):
 def test_catalog_mapping_complete(self):
  self.assertEqual(set(json.loads((B/'item_icon_map.json').read_text())['items']),set(CAT['items']))
 def test_all_png_valid(self):
  with zipfile.ZipFile(B/'item_icons.zip') as z:
   self.assertEqual(len(z.namelist()),4334)
   for n in z.namelist():
    with self.subTest(n=n):
     with Image.open(io.BytesIO(z.read(n))) as image:image.verify()
 def test_coverage(self):
  items=json.loads((B/'item_icon_map.json').read_text())['items'];r=json.loads((B/'item_icon_coverage.json').read_text())
  with zipfile.ZipFile(B/'item_icons.zip') as z:
   for sid,row in items.items():self.assertEqual(row['original_available'],row['icon']+'.png' in z.NameToInfo)
  self.assertEqual(r['items_with_original_images'],9855);self.assertEqual(r['items_with_missing_icons'],1432)

if __name__=='__main__':unittest.main(verbosity=2)
