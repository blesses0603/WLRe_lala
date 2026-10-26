"""1262 ItemBox.AddItemByItemSave: preferred slot, stack cap and nonstacked objects."""
from wlre.paths import RESOURCE_ROOT
import json,copy
STACKABLE=json.loads(RESOURCE_ROOT.joinpath('item_stackable.json').read_text(encoding='utf-8'))['items']

def add_item(inventory,value):
    items=copy.deepcopy(inventory['items']);sid=value['item_id'];count=value['count'];preferred=value['index']
    def fail(reason):
        inventory.update(reliable=False,sync_error=reason)
        return False
    if (type(sid) is not int or not 1 <= sid <= 65535
            or type(preferred) is not int or not 0 <= preferred <= 255
            or type(count) is not int or not 1 <= count <= 255):
        return fail('新增物品欄位不完整')
    capacity=inventory.get('capacity',255)
    # ItemData may contain newer 1275 IDs missing from the 1262
    # stackability table. Accept only an explicit free server slot with
    # a single unit; all other cases require validated stack metadata or
    # a fresh authoritative S23-5 snapshot.
    if str(sid) not in STACKABLE:
        if (type(capacity) is int and 1 <= preferred <= capacity
                and str(preferred) not in items and count == 1):
            items[str(preferred)] = {**value, 'index': preferred, 'count': 1}
            inventory['items'] = items
            return True
        return fail('新版物品沒有經驗證的堆疊規則，等待背包重新同步')
    def empty():
        if preferred and str(preferred) not in items:return preferred
        return next((i for i in range(1,capacity+1) if str(i) not in items),None)
    if STACKABLE[str(sid)]:
        target=items.get(str(preferred)) if preferred else next((v for v in items.values() if v['item_id']==sid and v['count']<200),None)
        if target:
            if target['item_id']!=sid:return fail('堆疊物品格位不符')
            amount=min(count,200-target['count']);target['count']+=amount;count-=amount
        while count:
            index=empty()
            if index is None:return fail('新增堆疊物品時包包格位不足')
            amount=min(count,200);items[str(index)]={**value,'index':index,'count':amount};count-=amount
    else:
        for _ in range(count):
            index=empty()
            if index is None:return fail('新增物品時包包格位不足')
            items[str(index)]={**value,'index':index,'count':1}
    inventory['items']=items
    return True
