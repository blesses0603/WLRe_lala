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

