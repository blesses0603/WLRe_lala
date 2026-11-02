"""Explicit garage/cupboard moves from UIRoomStorage.lua; server owns quantities."""
import copy
import math
import time

from wlre.core.state_ownership import writes
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.coordination import reason as coordination_reason
from wlre.services.items import reservations


def total(bucket,item_id):
    return sum(row['count'] for row in bucket.get('items',{}).values() if row['item_id']==item_id)


def is_stackable(item_id,bucket=None,item=None):
    from wlre.core.inventory_updates import STACKABLE
    return (STACKABLE.get(str(item_id)) is True or bool(item and item.get('count',0)>1)
            or bool(bucket and any(row['item_id']==item_id for row in bucket.get('items',{}).values())))


def free_capacity(bucket,item_id,count,stack_limit,stackable):
    capacity=bucket.get('capacity')
    if type(capacity) is not int or capacity<1:raise ProtocolError('目的容器容量尚未同步')
    room=sum(max(0,stack_limit-row['count']) for row in bucket['items'].values()
             if row['item_id']==item_id) if stackable else 0
    needed=math.ceil(max(0,count-room)/stack_limit) if stackable else count
    if len(bucket['items'])+needed>capacity:raise ProtocolError('目的容器空間不足')


def plan_transfer(state,command):
    action=command.get('action');target=command.get('target')
    if action not in ('deposit','withdraw') or target not in ('garage','materials'):
        raise ProtocolError('儲藏存取指令無效')
    if state.phase!='world_ready' or not state.player.get('role_id'):
        raise ProtocolError('請先完成角色登入')
    storage=state.room_storage
    if storage.get('pending') or storage.get('uncertain'):
        raise ProtocolError('儲藏操作尚未確認，請勿重複送出；結果不明時需重新登入')
    pause=coordination_reason(state,'room_storage')
    if pause:raise ProtocolError(pause)
    inv=state.inventory;bucket=storage[target]
    if not all(b.get('ready') and b.get('reliable',True) for b in (inv,bucket)):
        raise ProtocolError('請等待背包與儲藏空間完整同步')
    if ('bag_revision' in command and command['bag_revision']!=inv.get('revision')
            or 'storage_revision' in command and command['storage_revision']!=storage['revision']):
        raise ProtocolError('物品資料已更新，請重新選取')
    index=command.get('index');count=command.get('count')
    if type(index) is not int or type(count) is not int or not 1<=count<=65535:
        raise ProtocolError('格位與存取數量無效')
    source=inv if action=='deposit' else bucket
    destination=bucket if action=='deposit' else inv
    maximum=255 if action=='deposit' or target=='garage' else 65535
    if not 1<=index<=maximum:raise ProtocolError('來源格位超出範圍')
    item=source['items'].get(str(index))
    if not item or item['item_id']!=command.get('item_id'):
        raise ProtocolError('所選物品已變更，請重新選取')
    if count>reservations.available(source,index):raise ProtocolError('物品數量不足或仍被其他功能保留')
    if item.get('locked') or item.get('limited_time') or item.get('available_time'):
        raise ProtocolError('鎖定或有使用期限的物品不在本次存取範圍')
    stackable=is_stackable(item['item_id'],storage['materials'] if target=='materials' else None,item)
    if action=='deposit' and target=='materials':
        if not stackable:raise ProtocolError('雜物櫃只能存入已確認可堆疊的物品')
        if any(item.get(k,0) for k in ('enhance_level','magic_spar','beat_level','design_id')):
            raise ProtocolError('附加屬性的物品不能存入雜物櫃')
    if action=='deposit' and item['item_id']==34977:
        raise ProtocolError('超空間袋入口道具不可存入儲藏空間')
    limit=storage.get('material_stack_limit') if action=='deposit' and target=='materials' else 200
    if type(limit) is not int or not 1<=limit<=65535:raise ProtocolError('雜物櫃堆疊上限尚未同步')
    free_capacity(destination,item['item_id'],count,limit,stackable)
    writer=Writer()
    if target=='garage':
        if count>255:raise ProtocolError('儲藏室單次數量超出一個格位')
        packet=Packet(62,18 if action=='deposit' else 19,writer.u8(1).u8(index).u8(count).build())
    elif action=='deposit':
        if count>255:raise ProtocolError('存入數量超出背包格位上限')
        packet=Packet(62,52,writer.u8(1).u8(1).u8(index).u8(count).build())
    else:
        parts=math.ceil(count/200)
        if parts>255:raise ProtocolError('單次取出最多 255 組，請分次操作')
        writer.u8(2).u8(parts)
        remaining=count
        while remaining:
            used=min(200,remaining);writer.u16(index).u8(used);remaining-=used
        packet=Packet(62,52,writer.build())
    allocation={'index':index,'item_id':item['item_id'],'count':count}
    return packet,{'action':action,'target':target,'index':index,'count':count,
        'item':copy.deepcopy(item),'destination_before':total(destination,item['item_id']),
        'allocation':allocation,'ack':False}


class RoomStorageTransfer:
    timeout=15

    def __init__(self):self.pending=None

    @writes('room_storage')
    def command(self,state,command,now=None):
        if self.pending:raise ProtocolError('儲藏操作等待伺服器確認')
        packet,pending=plan_transfer(state,command)
        source=state.inventory if pending['action']=='deposit' else state.room_storage[pending['target']]
        reservations.acquire(source,'storage',[pending['allocation']],exclusive=True)
        pending['due']=(time.monotonic() if now is None else now)+self.timeout
        self.pending=pending
        state.room_storage.update(pending=pending['action'],status='已送出存取，等待移動結果與兩邊庫存確認')
        state.room_storage['revision']+=1
        return [packet]

    def buckets(self,state,pending):
        inv=state.inventory;bucket=state.room_storage[pending['target']]
        return (inv,bucket) if pending['action']=='deposit' else (bucket,inv)

    def unchanged(self,state,pending):
        source,destination=self.buckets(state,pending)
        return (source['items'].get(str(pending['index']))==pending['item']
                and total(destination,pending['item']['item_id'])==pending['destination_before'])

    @writes('room_storage')
    def observe(self,event,state):
        p=self.pending
        if p is None or state.room_storage.get('uncertain'):return
        if event['type']=='storage_move_result':
            p['ack']=event['result']==(1 if p['action']=='deposit' else 2)
        if event['type']=='storage_error':
            if self.unchanged(state,p):
                source,_=self.buckets(state,p);reservations.release(source,'storage')
                self.pending=None
                state.room_storage.update(pending=None,status=f"伺服器拒絕存取（代碼 {event['error_code']}）")
                state.room_storage['revision']+=1
            else:self.mark_uncertain(state,'伺服器回報存取錯誤，庫存已變動；請重新登入同步')
            return
        source,destination=self.buckets(state,p)
        item=source['items'].get(str(p['index']));remaining=p['item']['count']-p['count']
        source_ok=(item is None and remaining==0 or item is not None
                   and reservations.identity(item)==reservations.identity(p['item'])
                   and item['count']==remaining)
        destination_ok=total(destination,p['item']['item_id'])==p['destination_before']+p['count']
        if p['ack'] and source_ok and destination_ok and source.get('reliable') and destination.get('reliable'):
            reservations.release(source,'storage');self.pending=None
            label='存入' if p['action']=='deposit' else '取出'
            state.room_storage.update(pending=None,status=label+'成功，兩邊庫存已確認')
            state.room_storage['revision']+=1

    @writes('room_storage')
    def mark_uncertain(self,state,reason):
        if self.pending:
            source,_=self.buckets(state,self.pending)
            reservations.uncertain(source,'storage')
            source['reliable']=False
        state.inventory['reliable']=False
        state.room_storage.update(uncertain=True,status=reason)
        state.room_storage['revision']+=1

    @writes('room_storage')
    def tick(self,state,now=None):
        now=time.monotonic() if now is None else now
        if self.pending and now>=self.pending['due'] and not state.room_storage['uncertain']:
            self.mark_uncertain(state,'存取回覆逾時，已停止重送；請重新登入同步')
        return []

    @writes('room_storage')
    def disconnect(self,state):
        if self.pending:self.mark_uncertain(state,'連線結束，存取結果尚未確認；請重新登入同步')
