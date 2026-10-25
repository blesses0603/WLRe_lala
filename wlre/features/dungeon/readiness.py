"""Normal dungeon roster/room UI readiness.

Only derives disabled/enabled button state from server snapshots. Does not
send network packets or relax the authoritative command service.
"""


class DungeonRoomReadinessMixin:
    def render_dungeon_readiness(self, data, other, live, member_data,
                                 current_room, local_role_id, local_scene,
                                 activity_blocked):
        # Normal-dungeon start is host only. S85-4 roster must agree with
        # the room count, and the official StageData minimum must be met.
        stage = next((record for record in self.catalog_records
                      if record['kind'] == 1 and
                      record['map_id'] == current_room.get('room_id')), None)
        valid_roster = (type(current_room.get('members')) is int
                        and current_room['members'] == len(member_data)
                        and any(member.get('role_id') == local_role_id
                                for member in member_data))
        min_reached = (stage is not None and valid_roster
                       and stage['min_members'] <= len(member_data)
                       <= stage['max_members'])
        self._start_ready = (
            not self.cooperative and bool(live) and min_reached
            and data.get('phase') == 'waiting'
            and current_room.get('host_id') == local_role_id
            and not any(part.get(k) is not None
                        for part in (data, other)
                        for k in ('create_pending', 'join_pending',
                                  'leave_pending', 'standby_pending', 'start_pending', 'enter_pending'))
            and not any(part.get(k)
                        for part in (data, other)
                        for k in ('create_uncertain', 'join_uncertain',
                                  'leave_uncertain', 'standby_uncertain', 'start_uncertain', 'enter_uncertain')))
        self._enter_ready = (
            not self.cooperative and bool(live) and not activity_blocked
            and data.get('phase') == 'started'
            and type(local_scene) is int and local_scene > 0
            and local_scene != current_room.get('room_id')
            and stage is not None
            and any(member.get('role_id') == local_role_id for member in member_data)
            and not other.get('room')
            and not any(part.get(k) is not None
                        for part in (data, other)
                        for k in ('create_pending', 'join_pending', 'leave_pending',
                                  'standby_pending', 'start_pending', 'enter_pending'))
            and not any(part.get(k)
                        for part in (data, other)
                        for k in ('create_uncertain', 'join_uncertain', 'leave_uncertain',
                                  'standby_uncertain', 'start_uncertain', 'enter_uncertain')))
