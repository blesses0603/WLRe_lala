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


class CooperativeRoomStatusMixin:
    """Server-snapshot cooperative standby explanation (UI only)."""

    def render_cooperative_standby(self, live, data, current_room, member_data,
                                   host_id, local_role_id, room_capacity,
                                   reward_locked, activity_blocked):
        if self.cooperative:
            if not live:
                explanation = '尚未登入'
            elif not current_room:
                explanation = '尚未加入協力房間'
            elif data.get('create_pending') is not None:
                explanation = '創房仍待伺服器確認；請勿重複創房'
            elif data.get('create_uncertain'):
                explanation = '創房結果仍不明；請重新登入同步，不要重複扣點'
            elif data.get('standby_pending') is not None:
                explanation = '已送出準備要求，等待伺服器房間狀態回覆'
            elif data.get('standby_uncertain'):
                explanation = '準備結果不明；請重新登入確認'
            elif not member_data or host_id != local_role_id:
                explanation = '目前不是伺服器確認的房主，只有房主可開始'
            elif type(room_capacity) is not int or room_capacity <= 0:
                explanation = '房間容量尚未同步'
            elif len(member_data) < room_capacity:
                explanation = '等待成員到齊：%d/%d 人' % (len(member_data), room_capacity)
            elif data.get('phase') != 'waiting':
                explanation = ('戰後房間尚未恢復準備狀態；確認獎勵後才可離房'
                               if data.get('phase') == 'matched'
                               else '房間階段：%s，尚不能開始' % data.get('phase'))
            elif reward_locked or activity_blocked:
                explanation = '其他活動或獎勵操作尚未結束'
            elif self._standby_ready:
                explanation = '房主與成員 %d/%d 已確認，可以按準備／開始配對' % (
                    len(member_data), room_capacity)
            else:
                explanation = '有其他房間操作未確認；請查看上方狀態'
            self.standby_note.set('協力準備：' + explanation)
