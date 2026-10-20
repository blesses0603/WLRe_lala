"""Serialized post-battle maintenance; no assumed success or timeout retries."""
from wlre.core.state_ownership import writes
from wlre.services.items import reservations
from wlre.services.coordination import reason as coordination_reason
import copy
from wlre.services.items.maintenance import backpack_stock, cleanup_action, cleanup_packet, repair_packet
from wlre.services.items.combat_resources import CAT, item_name
from wlre.services.battle.combat import BROKEN


def identity(item):
    return item.get('item_id'),item.get('serial'),item.get('serial_version')


def equipment(state,npc,index):
    profile=state.knowledge['player'] if not npc else state.knowledge['companions'].get(str(npc),{})
    equips=profile.get('equips',[])
    return equips[index-1] if 1<=index<=len(equips) else {}


def repair_targets(state,threshold):
    profiles=[(0,state.knowledge['player'])]
    profiles.extend((p['index'],p) for p in state.knowledge['companions'].values()
                    if p.get('npc_id')==state.knowledge.get('active_npc_id'))
    for npc,profile in profiles:
        for i,equip in enumerate(profile.get('equips',[]),1):
            sid=equip.get('item_id');data=CAT['items'].get(str(sid),{});damage=equip.get('damage')
            # Automated requests target ordinary worn equipment only. Special,
            # timed, broken and indestructible/custom-use gear is not guessed.
            if not sid or sid in BROKEN or sid==25746 or data.get('special')!=0:continue
            if data.get('fit_type') not in (1,2,3,4,5,6):continue
            if equip.get('locked') or equip.get('available_time') or equip.get('limited_time'):continue
            if type(damage) is not int or not 0<damage<250 or 250-damage>threshold:continue
            yield {'npc_index':npc,'equip_index':i,**copy.deepcopy(equip)}


class PostBattleMaintenance:
    timeout=20
    settle_delay=.5

    def __init__(self):
        self.pending=None;self.uncertain=False;self.settle_key=None;self.settle_due=0
        self.trace_key=None;self.trace_at=None

    @writes('maintenance')
    def status(self,state,text,**fields):
        value={**state.maintenance,'status':text,'uncertain':self.uncertain,**fields}
        if value!=state.maintenance:state.maintenance=value

    @writes('maintenance')
    def fail(self,state,logic,text):
        reservations.uncertain(state.inventory,'maintenance')
        self.uncertain=True;state.inventory['use_failed']=True
        self.status(state,text+'；請重新登入同步',checking=False)
        logic.auto_battle.stop(state,text,source='maintenance_uncertain');logic.roaming.stop(state,logic.movement,text)

    @writes('maintenance')
    def observe(self,event,state):
        p=self.pending
        if not p or self.uncertain:return
        kind=event['type']
        if kind=='sale_notice' and event['result']==0 and p['action']=='sell':
            p['failure']='伺服器回覆販售失敗';return
        if kind=='bag_sell' and p['action']=='sell' and event['index']==p['index']:
            if event['count']!=p['count']:p['failure']='販售回覆數量不符'
            else:p['ack']=True
        if kind=='bag_delete' and event['index']==p['index']:
            if p['action']=='repair' and event['count']!=1:p['failure']='修理道具扣除數量不符'
            if p['action']=='delete':
                if event['count']!=p['count']:p['failure']='丟棄回覆數量不符'
                else:p['ack']=True
        item=state.inventory['items'].get(str(p['index']))
        same=item and identity(item)==identity(p['before'])
        if kind in ('bag_snapshot','bag_sell','bag_delete','bag_damage','bag_broken'):
            expected=p['before']['count']-p['count']
            spent=(item is None and expected==0 or same and item['count']==expected)
            if p['action']=='repair':
                if item is None and expected>0 or same and item['count']<expected:p['failure']='修理道具扣除數量不符'
                spent=spent or same and item.get('damage',0)>p['before'].get('damage',0)
            if spent:p['spent']=True

    @writes('maintenance')
    def tick(self,state,logic,now):
        if self.pending:
            p=self.pending
            if self.uncertain:return []
            if state.player.get('role_id')!=p['owner']:
                self.fail(state,logic,'修理／整理角色已變更');return []
            item=state.inventory['items'].get(str(p['index']))
            if item is not None and identity(item)!=identity(p['before']):
                self.fail(state,logic,'修理／整理背包格位已被替換');return []
            if p['action']=='repair':
                target=equipment(state,p['target']['npc_index'],p['target']['equip_index'])
                if identity(target)!=identity(p['target']):
                    self.fail(state,logic,'等待修復的裝備已被替換');return []
                confirmed=p['spent'] and target.get('damage')==0
            else:confirmed=p['spent'] and p['ack']
            if p.get('failure') or not state.inventory.get('reliable'):
                self.fail(state,logic,p.get('failure') or '修理／整理背包資料失效');return []
            if confirmed:
                self.pending=None;reservations.release(state.inventory,'maintenance')
                self.status(state,'已確認'+{'repair':'裝備修復與道具耗用','sell':'販售扣料','delete':'丟棄扣料'}[p['action']],
                            pending=None,checking=False,completed=state.maintenance.get('completed',0)+1)
                self.settle_key=None
            elif now>=p['due']:self.fail(state,logic,'修理／整理回覆逾時，未重送')
            return []
        if state.maintenance.get('checking'):self.status(state,state.maintenance['status'],checking=False)
        if self.uncertain or not logic.auto_battle.enabled or not logic.world_acknowledged:return []
        config=logic.auto_battle.settings['maintenance']
        if not config['repair_enabled'] and not config['cleanup_enabled']:return []
        if not state.battle_count or coordination_reason(state,'maintenance') or state.inventory.get('use_failed'):return []
        inv=state.inventory
        if not inv.get('ready') or not inv.get('reliable'):
            self.status(state,'等待背包可靠同步');return []
        key=(state.battle_count,inv.get('revision'),repr(config))
        if key!=self.settle_key:
            self.settle_key=key;self.settle_due=now+self.settle_delay
        if now<self.settle_due:
            logic.movement.stop(state,'等待戰後背包資料安定')
            self.status(state,'等待戰後背包資料安定',checking=True);return []
        stock=backpack_stock(inv)
        action=None;target=None;chosen=None;count=1
        repair_missing=False
        if config['repair_enabled']:
            target=next(repair_targets(state,config['repair_below']),None)
            if target:
                for sid in config['repair_items']:
                    if sid not in stock:continue
                    chosen=next(((int(index),item) for index,item in sorted(inv['items'].items(),key=lambda pair:int(pair[0]))
                                 if item['item_id']==sid and self.slot_available(inv,index)
                                 and type(item.get('damage')) is int and item['damage']<250),None)
                    if chosen:action='repair';break
                if not chosen:repair_missing=True
        if not chosen and config['cleanup_enabled']:
            protected=set(config['repair_items'])
            if logic.auto_battle.settings.get('field_heal'):
                for recovery in logic.auto_battle.settings['recovery'].values():protected.update(recovery['items'])
            for sid in config['cleanup_items']:
                if not sid or sid in protected or sid not in stock:continue
                action=cleanup_action(sid)
                if not action:continue
                chosen=next(((int(index),item) for index,item in sorted(inv['items'].items(),key=lambda pair:int(pair[0]))
                             if item['item_id']==sid and self.slot_available(inv,index)),None)
                if chosen:
                    count=min(255,chosen[1]['count']);target=None;break
        if not chosen:
            self.status(state,'需修復裝備，但背包內指定修理道具不足' if repair_missing else '戰後修理／整理檢查完成',checking=repair_missing)
            if repair_missing:logic.movement.stop(state,'等待補充指定修理道具')
            return []
        index,item=chosen
        packet=repair_packet(target,index,item['item_id']) if action=='repair' else cleanup_packet(action,index,count)
        reservations.acquire(inv,'maintenance',[{'index':index,'item_id':item['item_id'],'count':count}],exclusive=True)
        self.pending={'action':action,'index':index,'count':count,'before':copy.deepcopy(item),'target':target,
                      'owner':state.player.get('role_id'),'due':now+self.timeout,'spent':False,'ack':False}
        logic.movement.stop(state,'等待戰後修理／整理確認')
        label={'repair':'修理','sell':'販售','delete':'丟棄'}[action]
        self.status(state,'等待'+label+'回覆：'+item_name(item['item_id']),
                    checking=False,pending={'action':action,'index':index,'item_id':item['item_id'],'count':count})
        return [packet]

    @staticmethod
    def slot_available(inv,index):
        item=inv['items'][str(index)]
        return (item['count']>0 and not item.get('locked') and not item.get('available_time') and not item.get('limited_time')
                and reservations.available(inv,index)==item['count'])
