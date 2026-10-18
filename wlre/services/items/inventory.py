"""Server-backed bag updates and shared reservation accounting."""
from wlre.core.inventory_updates import add_item
from wlre.network.wire import ProtocolError
from wlre.services.items.catalog import item_name
from wlre.services.items import reservations
from wlre.services.items.reservations import available

def apply_inventory(state,event):
    kind=event['type'];inv=state.inventory
    if kind=='bag_snapshot':
        fresh={'ready':True,'reliable':True,'capacity':event['capacity'],'items':{},'reserved':{},
               'revision':inv.get('revision',0)+1,'use_failed':False,'field_supply':inv.get('field_supply',{}),'alchemy_slots':list(inv.get('alchemy_slots',[])),
               'expedition_slots':list(inv.get('expedition_slots',[])),
               'maintenance_slots':list(inv.get('maintenance_slots',[]))}
        for value in event['items']:
            if not add_item(fresh,dict(value)):break
        reservations.refreshed(inv,fresh)
        state.inventory=fresh
    elif kind=='bag_add':
        add_item(inv,dict(event['item']));inv['revision']+=1
    elif kind in ('bag_delete','bag_sell'):
        index=str(event['index']);value=inv['items'].get(index);count=event['count']
        if not value or count>value['count']:inv.update(reliable=False,sync_error='物品扣除數量或格位不符')
        elif value:
            value['count']-=count
            if not value['count']:inv['items'].pop(index)
        reservations.consumed(inv,index,count);inv['revision']+=1
    elif kind=='bag_damage':
        item=inv['items'].get(str(event['index']))
        if item:
            item['damage']=event['damage'];inv['revision']+=1
    elif kind=='bag_broken':
        apply_inventory(state,{'type':'bag_delete','index':event['index'],'count':1})
    else:return False
    return True

def allocate(inv,item_id,count):
    if not inv.get('ready') or not inv.get('reliable'):raise ProtocolError('包包資料尚未同步或已失效')
    result=[]
    for index,value in sorted(inv['items'].items(),key=lambda x:int(x[0])):
        if str(index) in inv.get('alchemy_slots',[]):continue
        if value['item_id']!=item_id:continue
        amount=min(count,available(inv,index))
        if amount:result.append({'index':int(index),'count':amount,'item_id':item_id});count-=amount
        if not count:return result
    raise ProtocolError(f'{item_name(item_id)}數量不足或仍待伺服器扣除')

def reserve(state,allocations,owner='battle',*,exclusive=False):
    reservations.acquire(state.inventory,owner,allocations,exclusive=exclusive)
