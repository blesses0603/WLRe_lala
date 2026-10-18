"""One bag hold registry for every consumer; legacy counters are projections.

A request holds item identity and quantities until its service confirms all
replies. Stop/timeout never frees an uncertain hold. Reconnect creates new State.
"""
import copy
from wlre.network.wire import ProtocolError

OWNERS=frozenset(('battle','field_supply','alchemy','crafting','expedition','maintenance'))
SLOT_FIELDS={'alchemy':'alchemy_slots','expedition':'expedition_slots','maintenance':'maintenance_slots'}


def identity(item):return item.get('item_id'),item.get('serial'),item.get('serial_version')

def locked(inv,index):
    key=str(index)
    return (any(key in inv.get(field,[]) for field in SLOT_FIELDS.values()) or
            any(row['index']==key and (row['exclusive'] or row.get('uncertain'))
                for rows in inv.get('holds',{}).values() for row in rows))


def available(inv,index):
    key=str(index)
    if locked(inv,key):return 0
    return max(0,inv.get('items',{}).get(key,{}).get('count',0)-inv.get('reserved',{}).get(key,0))


def _slots(inv,owner):
    field=SLOT_FIELDS.get(owner)
    if field:inv[field]=list(dict.fromkeys(row['index'] for row in inv.get('holds',{}).get(owner,[])))


def acquire(inv,owner,allocations,*,exclusive=False):
    """Validate the entire batch before any mutation, including duplicate slots."""
    if owner not in OWNERS:raise ValueError('未知的背包保留用途')
    if not inv.get('ready') or not inv.get('reliable'):raise ProtocolError('包包資料尚未同步或已失效')
    combined={}
    for value in allocations:
        index=str(value['index']);count=value['count'];item=inv['items'].get(index)
        if type(count) is not int or count<=0:raise ProtocolError('背包保留數量必須為正整數')
        if index in inv.get('alchemy_slots',[]):raise ProtocolError('此格仍等待煉金材料扣除回覆')
        if not item or item['item_id']!=value.get('item_id',item['item_id']):raise ProtocolError('包包物品已變更')
        previous=next((r for r in inv.get('holds',{}).get(owner,[]) if r['index']==index),None)
        if previous and tuple(previous['identity'])!=identity(item):raise ProtocolError('包包格位序號已變更')
        if any(index==r['index'] for other,rows in inv.get('holds',{}).items() if other!=owner for r in rows):
            raise ProtocolError('此格仍等待其他功能確認')
        if available(inv,index)<combined.get(index,0)+count:raise ProtocolError('包包數量已變更或仍等待操作確認')
        combined[index]=combined.get(index,0)+count
    holds=inv.setdefault('holds',{}).setdefault(owner,[])
    for index,count in combined.items():
        item=inv['items'][index]
        row=next((row for row in holds if row['index']==index),None)
        if row:
            if tuple(row['identity'])!=identity(item):raise ProtocolError('包包格位序號已變更')
            row['count']+=count;row['remaining']+=count
        else:
            holds.append({'index':index,'identity':list(identity(item)),'count':count,'remaining':count,
                          'before':item['count'],'exclusive':exclusive,'uncertain':False})
        inv.setdefault('reserved',{})[index]=inv.get('reserved',{}).get(index,0)+count
    _slots(inv,owner)


def release(inv,owner):
    """Only call after a definitive confirmation (or before any packet is sent)."""
    for row in inv.setdefault('holds',{}).pop(owner,[]):
        key=row['index'];inv['reserved'][key]=max(0,inv['reserved'].get(key,0)-row['remaining'])
    _slots(inv,owner)


def uncertain(inv,owner):
    for row in inv.get('holds',{}).get(owner,[]):row['uncertain']=True


def consumed(inv,index,count):
    key=str(index);remaining=count
    for owner,rows in list(inv.get('holds',{}).items()):
        for row in rows:
            if row['index']!=key:continue
            use=min(remaining,row['remaining']);row['remaining']-=use;remaining-=use
        # Battle items require only the authoritative deduction to release.
        if owner=='battle':
            inv['holds'][owner]=[row for row in rows if row['remaining']]
            if not inv['holds'][owner]:inv['holds'].pop(owner)
    inv['reserved'][key]=max(0,inv['reserved'].get(key,0)-count)


def refreshed(old,fresh):
    fresh['holds']=copy.deepcopy(old.get('holds',{}))
    for owner,rows in fresh['holds'].items():
        for row in rows:
            item=fresh['items'].get(row['index']);expected=row['before']-row['count']
            if item is None:
                if expected>0:
                    row['uncertain']=True;fresh.update(reliable=False,sync_error='保留物品格位遺失，請重新登入同步')
                row['remaining']=0
            elif tuple(row['identity'])!=identity(item):
                row['uncertain']=True;fresh.update(reliable=False,sync_error='保留物品序號已變更，請重新登入同步')
            else:row['remaining']=min(row['remaining'],max(0,item['count']-expected))
            if row.get('uncertain'):
                fresh.update(reliable=False,sync_error=fresh.get('sync_error','先前背包操作未確認，請重新登入同步'))
            key=row['index'];fresh['reserved'][key]=fresh['reserved'].get(key,0)+row['remaining']
        _slots(fresh,owner)
    # Completed battle deductions have no second confirmation to await.
    if 'battle' in fresh['holds']:
        fresh['holds']['battle']=[row for row in fresh['holds']['battle'] if row['remaining'] or row['uncertain']]


def checkpoint(inv):
    return {key:copy.deepcopy(inv.get(key,{} if key in ('holds','reserved') else []))
            for key in ('holds','reserved',*SLOT_FIELDS.values())}

def restore(inv,saved):
    for key,value in saved.items():inv[key]=copy.deepcopy(value)
