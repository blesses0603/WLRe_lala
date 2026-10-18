"""Read-only server-confirmed room storage, derived from 1262 RoomStorage.lua.

62-7/11/13: garage full ItemSaveData records and changes.
62-57: materials cupboard compact records.
62-71/72/73/74/75: storage result and capacities.

No outbound deposit/withdraw requests are generated here.
"""
from wlre.network.wire import Reader, ProtocolError
from wlre.network.live_data import item_save


def defaults():
    return {
        'garage': {'ready': False, 'reliable': True, 'items': {}, 'capacity': None},
        'materials': {'ready': False, 'reliable': True, 'items': {}, 'capacity': None},
        'material_stack_limit': None,
        'parameters_ready': False,
        'revision': 0,
        'last_result': None,
        'last_error': None,
    }


def decode_storage(packet):
    if packet.main != 62 or packet.sub not in (7, 11, 13, 25, 57, 71, 72, 73, 74, 75):
        return None
    r = Reader(packet.payload)
    event = {'main': 62, 'sub': packet.sub}
    sub = packet.sub
    if sub == 7:
        count = r.u8()
        # Lua: count(1), then count * [index(1) + ItemSaveData].
        entries = [item_save(r, r.u8()) for _ in range(count)]
        if len({v['index'] for v in entries}) != len(entries):
            raise ProtocolError('儲藏室初始化格位重複')
        event.update(type='storage_garage_initial', items=entries)
    elif sub == 11:
        event.update(type='storage_garage_add', item=item_save(r, r.u8()))
    elif sub == 13:
        event.update(type='storage_garage_delete', index=r.u8(), count=r.u8())
    elif sub == 57:
        kind = r.u8()
        if kind == 1:
            send_kind = r.u8()
            if send_kind not in (1, 2):
                raise ProtocolError('雜物櫃同步種類不明')
            count = r.u16() if send_kind == 1 else 1
            if count > r.remaining // 6:
                raise ProtocolError('雜物櫃物品數量不符')
            entries = [
                {'index': r.u16(), 'item_id': r.u16(), 'count': r.u16()}
                for _ in range(count)
            ]
            if send_kind == 1 and len({v['index'] for v in entries}) != len(entries):
                raise ProtocolError('雜物櫃初始化格位重複')
            event.update(type='storage_materials_initial' if send_kind == 1 else 'storage_materials_add', items=entries)
        elif kind == 2:
            event.update(type='storage_materials_delete', index=r.u16(), count=r.u16())
        else:
            raise ProtocolError('雜物櫃封包種類不明')
    elif sub == 71:
        event.update(type='storage_move_result', result=r.u8())
    elif sub == 72:
        event.update(type='storage_parameters', garage_space=r.u8(),
                     material_space=r.u16(), material_stack_limit=r.u16())
    elif sub in (73, 74, 75):
        event.update(type='storage_expanded', target={73: 'garage', 74: 'materials', 75: 'stack'}[sub],
                     value=r.u8() if sub == 73 else r.u16())
    elif sub == 25:
        kind, error_code = r.u8(), r.u8()
        if kind != 1:
            # 62-25 also carries other house error classes; do not mislabel them.
            return None
        event.update(type='storage_error', kind=kind, error_code=error_code)
    r.end()
    return event


def _add(bucket, item):
    index = str(item['index'])
    previous = bucket['items'].get(index)
    if previous and previous['item_id'] != item['item_id']:
        bucket['reliable'] = False
        return
    if previous:
        previous['count'] += item['count']
    else:
        bucket['items'][index] = dict(item)


def _delete(bucket, index, count):
    key = str(index)
    previous = bucket['items'].get(key)
    if not previous or count < 1 or count > previous['count']:
        bucket['reliable'] = False
        return
    previous['count'] -= count
    if previous['count'] == 0:
        bucket['items'].pop(key)


def apply_storage(state, event):
    kind = event['type']
    if not kind.startswith('storage_'):
        return
    storage = state.room_storage
    if kind in ('storage_garage_initial', 'storage_garage_add', 'storage_garage_delete'):
        bucket = storage['garage']
        if kind == 'storage_garage_initial':
            # The original Lua appends each S62-7 batch, rather than clearing.
            for entry in event['items']:
                _add(bucket, entry)
            bucket['ready'] = True
        elif kind == 'storage_garage_add':
            _add(bucket, event['item'])
        else:
            _delete(bucket, event['index'], event['count'])
    elif kind in ('storage_materials_initial', 'storage_materials_add', 'storage_materials_delete'):
        bucket = storage['materials']
        if kind == 'storage_materials_initial':
            for entry in event['items']:
                _add(bucket, entry)
            bucket['ready'] = True
        elif kind == 'storage_materials_add':
            for entry in event['items']:
                _add(bucket, entry)
        else:
            _delete(bucket, event['index'], event['count'])
    elif kind == 'storage_parameters':
        storage['garage']['capacity'] = event['garage_space']
        storage['materials']['capacity'] = event['material_space']
        storage['material_stack_limit'] = event['material_stack_limit']
        storage['parameters_ready'] = True
    elif kind == 'storage_expanded':
        target = event['target']
        if target == 'stack':
            storage['material_stack_limit'] = event['value']
        else:
            storage[target]['capacity'] = event['value']
    elif kind == 'storage_move_result':
        storage['last_result'] = event['result']
    elif kind == 'storage_error':
        storage['last_error'] = event['error_code']
    storage['revision'] += 1
