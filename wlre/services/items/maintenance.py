"""Backpack-only maintenance preferences and verified 1262 packet adapters."""
import copy
from wlre.network.wire import Packet, Writer
from wlre.network.wire import ProtocolError
from wlre.services.items.combat_resources import CAT, available


def defaults():
    return {'repair_enabled':False, 'repair_below':50, 'repair_items':[0,0],
            'cleanup_enabled':False, 'cleanup_items':[0]*15}


def is_repair(item_id):
    item=CAT['items'].get(str(item_id),{})
    return item.get('kind')==25 and item.get('special')==130


def validate(value):
    result=defaults()
    if not isinstance(value,dict) or set(value)-set(result):raise ProtocolError('未知修理／整理設定')
    result.update(copy.deepcopy(value))
    for key in ('repair_enabled','cleanup_enabled'):
        if type(result[key]) is not bool:raise ProtocolError('修理／整理開關須為布林值')
    if type(result['repair_below']) is not int or not 0<=result['repair_below']<=249:
        raise ProtocolError('裝備剩餘耐久門檻須為0～249（滿耐久250）')
    for key,size in (('repair_items',2),('cleanup_items',15)):
        values=result[key]
        if not isinstance(values,list) or len(values)!=size:raise ProtocolError('修理／整理格數錯誤')
        for sid in values:
            if type(sid) is not int or sid<0 or sid and str(sid) not in CAT['items']:
                raise ProtocolError('修理／整理物品無效')
            if sid and key=='repair_items' and not is_repair(sid):raise ProtocolError('物品不是已確認的修復道具')
    return result


def backpack_stock(inventory, repair=False):
    if not inventory.get('ready') or not inventory.get('reliable'):return {}
    counts={}
    for index,item in inventory.get('items',{}).items():
        if str(index) in inventory.get('alchemy_slots',[]) or inventory.get('reserved',{}).get(str(index),0):continue
        sid=item.get('item_id',0)
        if not sid or str(sid) not in CAT['items']:continue
        if item.get('locked') or item.get('available_time') or item.get('limited_time'):continue
        if repair and not is_repair(sid):continue
        count=available(inventory,str(index))
        if count>0:counts[sid]=counts.get(sid,0)+count
    return counts


def cleanup_action(item_id):
    data=CAT['items'].get(str(item_id),{})
    restrict=data.get('restrict')
    if type(restrict) is not int:return None
    if not restrict&16:return 'sell'
    if not restrict&128:return 'delete'
    return None


def cleanup_packet(action,index,count):
    if type(index) is not int or not 1<=index<=255 or type(count) is not int or not 1<=count<=255:
        raise ProtocolError('背包整理格位／數量無效')
    if action=='sell':return Packet(27,3,Writer().u8(index).u8(count).build())
    if action=='delete':return Packet(23,124,Writer().u8(index).u8(count).u8(2).build())
    raise ProtocolError('未知背包整理操作')


def repair_packet(target,index,item_id):
    return Packet(23,84,Writer().u8(2).u16(target['item_id']).u8(target['equip_index'])
                  .u8(target['npc_index']).u8(1).u16(index).u16(item_id).u16(1).build())
