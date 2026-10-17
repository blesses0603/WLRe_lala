"""One outstanding bag or storage heal across manual controls and AI; never retry uncertainty."""
import time
from wlre.network.wire import ProtocolError
from wlre.services.items.combat_resources import field_context

class FieldSupply:
    timeout=15
    def __init__(self):self.pending=None;self.uncertain=False;self.revision=0
    def check(self):
        if self.uncertain:raise ProtocolError('前次補給結果未確認；請重新登入同步，禁止重複使用補給')
        if self.pending:raise ProtocolError('前次補給尚待同一物品扣除與 HP／SP 回覆，請勿重複送出')
    def status(self,state,status,reason,item_id=None):
        self.revision+=1
        state.inventory['field_supply']={'status':status,'reason':reason,'item_id':item_id,'pending':bool(self.pending),'uncertain':self.uncertain}
    def begin(self,state,plan,target,now=None):
        self.check();now=time.monotonic() if now is None else now
        item=state.inventory['items'].get(str(plan['bag_index']))
        if not item or item['item_id']!=plan['item_id']:raise ProtocolError('補給物品已變更')
        self.pending={'index':plan['bag_index'],'item_id':plan['item_id'],'serial':item.get('serial'),'count':item['count'],'slot':f"{target['col']}:{target['row']}",'pid':target['pid'],'npc_index':target.get('npc_index',0),'owner':state.player.get('role_id'),'resource':plan['resource'],'before':target.get(plan['resource'],0),'due':now+self.timeout,'consumed':False,'restored':False,'failure':None}
        self.status(state,'pending','等待同一格物品扣除及同一對象 HP／SP 回覆',plan['item_id'])
    def begin_storage(self,state,plan,target,now=None):
        self.check();now=time.monotonic() if now is None else now
        balance=state.potion_storage.get(plan['resource'],{})
        if 'value' not in balance or balance['value']<plan['amount']:raise ProtocolError('儲存槽數量不足或尚未同步')
        self.pending={'source':'storage','index':None,'item_id':None,'slot':f"{target['col']}:{target['row']}",
            'pid':target['pid'],'npc_index':target.get('npc_index',0),'owner':state.player.get('role_id'),
            'resource':plan['resource'],'before':target.get(plan['resource'],0),'due':now+self.timeout,
            'balance':balance['value'],'amount':plan['amount'],'consumed':False,'restored':False,'failure':None}
        self.status(state,'pending','等待儲存槽使用回覆及同一對象 HP／SP 更新')
    def observe(self,event,state):
        p=self.pending
        if not p or self.uncertain:return
        kind=event['type'];resource=p['resource'];attribute=25 if resource=='hp' else 26
        if p.get('source')=='storage':
            balance=state.potion_storage.get(resource,{})
            if kind=='potion_balance' and event['resource']==resource and balance.get('value',p['balance'])<=p['balance']-p['amount']:p['consumed']=True
            if kind=='potion_used' and event['resource']==resource and p['npc_index'] in event['targets'] and not p['consumed']:
                if 'value' in balance:
                    state.potion_storage[resource]={**balance,'value':max(0,balance['value']-p['amount']),'revision':balance.get('revision',0)+1}
                p['consumed']=True
        item=state.inventory['items'].get(str(p['index']))
        same=item and item['item_id']==p['item_id'] and item.get('serial')==p['serial']
        if kind=='bag_delete' and event['index']==p['index'] and event['count']>0:
            if item is None or same and item['count']<=p['count']-1:p['consumed']=True
        elif kind=='bag_snapshot' and state.inventory.get('reliable') and same and item['count']<=p['count']-1:p['consumed']=True
        if kind=='item_use_result' and p.get('source')!='storage':
            matched=event.get('result')!=2 or (event.get('item_id')==p['item_id'] and event.get('npc_index')==p['npc_index'])
            if matched and event['result'] in (3,4):p['failure']='伺服器回覆補給失敗，請重新登入同步'
        health=False
        if kind=='attribute_set' and event.get('kind')==attribute:
            health=(p['npc_index']==0 and event.get('entity')=='self') or (p['npc_index']!=0 and event.get('entity')==f"follow:{p['npc_index']}" and event.get('human_kind')==4)
        elif kind=='player_combat_data' and p['npc_index']==0:health=True
        elif kind=='companion_snapshot' and p['npc_index']:
            health=any(v.get('index')==p['npc_index'] and v.get('npc_id')==p['pid'] for v in event.get('companions',[]))
        if health:
            context,_=field_context(state.snapshot());unit=context['battle_units'].get(p['slot'],{})
            if unit.get('pid')==p['pid'] and unit.get('npc_index',0)==p['npc_index'] and unit.get(resource,0)>p['before']:p['restored']=True
    def tick(self,state,now=None):
        p=self.pending
        if not p or self.uncertain:return None
        now=time.monotonic() if now is None else now
        context,_=field_context(state.snapshot());unit=context['battle_units'].get(p['slot'],{})
        reason=p['failure']
        if state.player.get('role_id')!=p['owner'] or unit.get('pid')!=p['pid'] or unit.get('npc_index',0)!=p['npc_index']:reason='補給對象已變更，前次結果未確認，請重新登入同步'
        if not reason and p['consumed'] and p['restored']:
            self.pending=None;self.status(state,'confirmed',('儲存槽使用及 HP／SP 回覆均已確認' if p.get('source')=='storage' else '物品扣除及 HP／SP 回覆均已確認'),p['item_id'])
        else:
            if not reason and now>=p['due']:reason='補給回覆逾時，已禁止續送；請重新登入同步'
            if not reason:return None
            self.uncertain=True;state.inventory['use_failed']=True
            self.status(state,'uncertain',reason,p['item_id'])
        return {'type':'field_supply_status',**state.inventory['field_supply']}
