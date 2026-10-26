"""Shared server-confirmed instance room list rendering.

The two modes intentionally share one list implementation and selection logic.
"""


class InstanceRoomListMixin:
    def render_room_list(self, data, live, local_role_id, details_fn):
        current_room = data.get('room') or {}
        rooms = data.get('rooms', ())
        if not live:
            self.room_list_note.set('尚未連線，請登入後更新房間清單')
        elif not data.get('ready'):
            self.room_list_note.set('尚未更新房間清單，請點選上方「更新房間清單」')
        elif rooms:
            self.room_list_note.set('伺服器已同步 %d 間房，點選房間即可加入' % len(rooms))
        else:
            self.room_list_note.set('伺服器目前沒有可加入的房間，可以選擇副本後自行建立')
        # Refresh a small, bounded list; never invent known dungeon names.
        previous = self.selected_room()
        key = (previous['room_id'], previous.get('sn')) if previous else None
        self.entries.delete(*self.entries.get_children())
        self._room_rows = list(rooms)
        matched = None
        for index, room in enumerate(rooms):
            room_id = room['room_id']
            capacity = room.get('capacity')
            count = room.get('members', 0)
            occupancy = '%s/%s 人' % (count, capacity) if capacity is not None else '%s 人' % count
            self.entries.insert('', 'end', iid='room_%s' % index, values=(
                '房間 #%s' % room_id,
                occupancy,
                '公開' if room.get('public') else '私人',
            ))
            if key == (room_id, room.get('sn')):
                matched = 'room_%s' % index
        if matched is not None:
            self.entries.selection_set(matched)
        self._update_room_buttons()
        if self.cooperative:
            self.standby_button.configure(
                text='取消準備' if current_room.get('standby') else '準備／開始配對')
            self.standby_button.state(
                ['!disabled'] if self._standby_ready else ['disabled'])
        current = data.get('room')
        if current is not None:
            count = len(data.get('members') or ())
            status = '目前房間 #%s' % current.get('room_id', '待確認')
            self.details.set('%s；已知成員 %s 人，階段：%s；%s%s' % (
                status, count, data.get('phase', '待確認'),
                data.get('status', '等待伺服器同步'),
                '；' + details_fn(data, self.cooperative, local_role_id)
                if details_fn(data, self.cooperative, local_role_id) else ''))
        elif self.cooperative and data.get('reward'):
            current_reward = data['reward']
            self.details.set('協力獎勵旗標 %s，已完成 %s／%s 場；%s' % (
                current_reward['reward_mark'], current_reward['win_stage'],
                current_reward['reward_count'],
                details_fn(data, True, local_role_id) or '以伺服器回覆為準'))
        else:
            self.details.set(
                details_fn(data, self.cooperative, local_role_id)
                or '未加入房間；進入、準備、領獎功能仍待正式伺服器驗證。')
