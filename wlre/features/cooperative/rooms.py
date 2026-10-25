"""Cooperative room headcount display based solely on server evidence."""


def cooperative_headcount_status(room, members, count, *, can_begin=False):
    capacity = room.get('capacity')
    if type(capacity) is not int or not 1 <= capacity <= 8:
        return '協力副本：房間容量尚未同步，暫不能判定是否滿員'
    prefix = '協力副本：目前 %d/%d 人' % (count, capacity)
    host = room.get('host_id')
    if host is None and count:
        host = members[0].get('role_id')
    verified = (isinstance(members, (list, tuple))
                and count <= capacity and bool(count)
                and members[0].get('role_id') == host
                and host is not None)
    if not verified:
        return prefix + '；伺服器房主／成員名單尚未完整同步'
    if count < capacity:
        return prefix + '，尚缺 %d 人（協力須滿員）' % (capacity - count)
    if room.get('standby') is True:
        return prefix + '，已滿員；房間已進入準備狀態'
    if can_begin:
        return prefix + '，已滿員；房主可以準備／開始配對'
    return prefix + '，已滿員；等待房主或其他開始條件確認'



def cooperative_count_selector(form, record):
    """Build the coop-only capacity selector without copying shared dialogs."""
    import tkinter as tk
    from tkinter import ttk
    count_var = tk.StringVar(value=str(record['min_members']))
    ttk.Label(form, text='協力房間人數').pack(anchor='w')
    ttk.Spinbox(form, from_=record['min_members'], to=record['max_members'],
                textvariable=count_var, width=8).pack(anchor='w', pady=(0, 8))
    return count_var


def cooperative_checked_count(raw, record):
    """Accept only a count within the verified catalog range; UI cannot bypass it."""
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    if count < record['min_members'] or count > record['max_members']:
        return None
    return count


def cooperative_create_fields(record, count):
    """Fields specific to coop creation; payment confirmation is never omitted."""
    return {'dungeon_id': record['id'], 'player_count': count,
            'confirm_cost': True}


def cooperative_join_fields():
    """Explicit acknowledgement of possible ticket/point consumption."""
    return {'confirm_cost': True}
