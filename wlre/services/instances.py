"""Authoritative read-only instance state from server S85 and S186 events."""
def _clear_main_round(data):
    data['objectives'] = {'targets': {}, 'boss': None, 'scores': {}}
    data['completed'] = False
    data['completion_source'] = None
    data['entered_scene'] = None
    data['battle_active'] = False


def _clear_coop_round(data):
    data['fight_count'] = None
    data['fight_consumed_battle'] = None
    data['last_fight_victory'] = None
    data['match_kind'] = None
    data['battle_active'] = False
    data['completed'] = False
    data['completion_source'] = None
    if not (data.get('claim_pending') or data.get('cancel_pending')
            or data.get('reward_uncertain')):
        data['received_awards'] = []
        data['mail_notice'] = False


def defaults():
    return {
        'main': {'ready': False, 'rooms': [], 'room': None, 'members': [],
                 'phase': 'idle', 'status': '尚未查詢房間', 'remaining_minutes': None,
                 'objectives': {}, 'completed': False,
                 'create_pending': None, 'create_uncertain': False, 'create_result': None,
                 'join_pending': None, 'join_uncertain': False, 'join_result': None,
                 'leave_pending': None, 'leave_uncertain': False, 'leave_result': None,
                 'list_updated_at': None,
                 'start_pending': None, 'start_uncertain': False, 'start_result': None,
                 'enter_pending': None, 'enter_uncertain': False, 'enter_result': None,
                 'entered_scene': None, 'battle_active': False,
                 'completion_source': None},
        'coop': {'ready': False, 'rooms': [], 'room': None, 'members': [],
                 'phase': 'idle', 'status': '尚未查詢房間', 'fight_count': None, 'fight_consumed_battle': None, 'last_fight_victory': None,
                 'reward': None, 'standby': None,
                  'create_attempt': None,
                 'standby_pending': None, 'standby_uncertain': False, 'standby_result': None,
                 'create_pending': None, 'create_uncertain': False, 'create_result': None,
                 'join_pending': None, 'join_uncertain': False, 'join_result': None,
                 'leave_pending': None, 'leave_uncertain': False, 'leave_result': None,
                 'list_updated_at': None, 'match_kind': None, 'battle_active': False,
                 'completed': False, 'completion_source': None,
                 'auto_claim_enabled': False, 'auto_claim_note': '',
                 'claim_pending': None, 'claim_result': None,
                 'cancel_pending': None, 'cancel_result': None,
                 'reward_uncertain': False, 'reward_handled_fingerprint': None,
                 'received_awards': [], 'mail_notice': False},
    }


def apply_instances(state, event):
    mode = event.get('mode')
    if mode not in ('main', 'coop') or not event.get('type', '').startswith('instance_'):
        # Existing battle/world events only inform instance state; no fake wins.
        from wlre.services.instance_entry import observe as observe_entry
        observe_entry(state, event)
        return
    data = state.instances[mode]
    kind = event['type']
    if kind == 'instance_room_list':
        data['rooms'] = list(event['rooms'])
        data['ready'] = True
        import time
        data['list_updated_at'] = time.monotonic()
        data['status'] = '已同步房間清單（%d 間）' % len(event['rooms'])
    elif kind == 'instance_result':
        code = event['code']
        # S85 / S186 result codes differ, and "success" is only a result
        # notification; room state is confirmed by S85-5 or S186-3.
        if mode == 'main':
            data['status'] = ('%s回覆：%s' % (event['action'], '成功，等待房間同步' if code == 0 else '拒絕代碼 %d' % code))
            if event['action'] == 'join' and code == 0 and data.get('room') is not None:
                data['status'] = '已加入一般副本房間（伺服器確認）'
            if event['action'] == 'create' and code == 0 and data.get('room') is not None:
                data['status'] = '房間建立完成（伺服器已同步）'
        else:
            data['status'] = ('協力創房／扣點已確認' if code == 9 and data.get('room') is not None
                              else '已加入協力房間（伺服器確認）' if code == 10 and data.get('room') is not None
                              else '協力事件通知：代碼 %d（待房間資料確認）' % code)
    elif kind == 'instance_phase':
        phase = event['kind']
        if phase in (2, 4):
            data['room'] = None
            data['members'] = []
            data['phase'] = 'idle'
            if mode == 'main':
                data['objectives'] = {}
                data['entered_scene'] = None
                data['battle_active'] = False
            else:
                data['fight_count'] = None
                data['fight_consumed_battle'] = None
                data['match_kind'] = None
                data['battle_active'] = False
            data['status'] = '已離開副本房間' if phase == 2 else '已被移出副本房間'
        elif phase == 1:
            if mode == 'main':
                _clear_main_round(data)
            data['room'] = {'room_id': event['room_id'], 'host_id': event['host_id'],
                            'members': event['count']}
            data['members'] = []
            data['phase'] = 'waiting'
            data['status'] = '已收到入房狀態，等待成員同步'
        elif phase == 3:
            data['phase'] = 'started'
            data['status'] = '伺服器通知副本開始'
        elif phase == 5:
            data['status'] = '伺服器確認移出成員'
    elif kind == 'instance_members':
        room_id = event['room_id']
        if mode == 'coop':
            old_room_id = (data.get('room') or {}).get('room_id')
            if old_room_id != room_id:
                _clear_coop_round(data)
                # Do not confuse a previous chest with a new session.
                # Unresolved reward operations must keep their evidence.
                if not (data.get('claim_pending') or data.get('cancel_pending')
                        or data.get('reward_uncertain')):
                    data['reward'] = None
                    data['reward_handled_fingerprint'] = None
                    data['claim_result'] = None
                    data['cancel_result'] = None
            data['room'] = {'room_id': room_id, 'kind': event['kind'],
                            'npc_id': event['npc_id'], 'capacity': event['capacity'],
                            'host_id': event.get('host_id'),
                            'standby': event['standby']}
            if data.get('phase') not in ('matched', 'combat') or old_room_id != room_id:
                data['phase'] = 'waiting'
            data['standby'] = event['standby']
            if data.get('phase') == 'waiting':
                data['status'] = '協力房間與成員已同步'
        elif data.get('room') is None or data['room'].get('room_id') != room_id:
            # Do not associate a room roster with an unrelated session.
            return
        data['members'] = list(event['members'])
    elif kind == 'instance_member_joined':
        room = data.get('room')
        if room is None or room['room_id'] != event['room_id']:
            return
        data['members'] = [m for m in data['members'] if m['role_id'] != event['role_id']]
        data['members'].append({'role_id': event['role_id']})
        room['members'] = event['count']
        data['status'] = '已有新成員加入'
    elif kind == 'instance_member_left':
        room = data.get('room')
        if room is None:
            return
        room.update(members=event['count'], host_id=event['host_id'])
        data['members'] = [m for m in data['members'] if m['role_id'] != event['role_id']]
        if event['role_id'] == state.player.get('role_id'):
            data['room'] = None
            data['members'] = []
            data['phase'] = 'idle'
        data['status'] = '伺服器確認成員離開'
    elif kind == 'instance_time':
        data['remaining_minutes'] = event['minutes']
    elif kind == 'instance_objective':
        # S85-10 supplies every count and role; no guessed kills or score.
        objectives = data.setdefault('objectives', {})
        targets = objectives.setdefault('targets', {})
        category = event['kind']
        if category == 1:
            row = targets.setdefault(event['index'], {})
            row['kills'] = min(event['kills'], row.get('required', event['kills']))
            row['last_killer'] = event['killer']
        elif category == 2:
            boss = objectives.get('boss') or {}
            if event['defeated']:
                boss['defeated'] = True
                boss['last_killer'] = event['killer']
                objectives['boss'] = boss
        elif category == 3:
            row = targets.setdefault(event['index'], {})
            row.update(npc_id=event['npc_id'], required=event['required'])
            row['kills'] = min(row.get('kills', 0), event['required'])
        elif category == 4:
            boss = objectives.get('boss') or {}
            boss['npc_id'] = event['npc_id']
            boss.setdefault('defeated', False)
            objectives['boss'] = boss
        elif category in (5, 6):
            key = 'normal' if category == 5 else 'boss'
            scores = objectives.setdefault('scores', {})
            for role_id in event['role_ids']:
                entry = scores.setdefault(str(role_id), {'normal': 0, 'boss': 0})
                entry[key] += 1
        data['status'] = '副本目標與成員積分已依 S85-10 同步'
    elif kind == 'instance_completed':
        data['completed'] = True
        data['completion_source'] = 'S85-15'
        data['phase'] = 'completed'
        data['status'] = '伺服器已確認一般副本完成；不需額外送出通關指令'
    elif kind == 'instance_min_players':
        data['status'] = '伺服器通知已達最低進入人數'
    elif kind == 'instance_new_info':
        subkind = event['kind']
        if subkind == 0:
            if (data.get('room') or {}).get('scene') != event['scene']:
                _clear_main_round(data)
            data['room'] = {'scene': event['scene'], 'host_id': event['host_id'],
                            'dungeon_kind': event['dungeon_kind'],
                            'organization_only': event['organization_only']}
            data['phase'] = 'new_instance'
            data['remaining_minutes'] = event['remaining']
            data['status'] = '新式副本基本資料已同步'
        elif subkind == 1:
            data['remaining_minutes'] = event['remaining']
        elif subkind == 2:
            data['member_count'] = event['count']
        elif subkind == 3:
            row = data.setdefault('objectives', {}).setdefault('targets', {}).setdefault(event['index'], {})
            row.update(npc_id=event['npc_id'], required=event['required'],
                       kills=min(event['kills'], event['required']))
        elif subkind == 4:
            row = data.setdefault('objectives', {}).setdefault('targets', {}).get(event['index'])
            if row is not None:
                row['kills'] = min(row.get('required', 0), row.get('kills', 0) + 1)
                row['last_killer'] = event['killer']
        elif subkind == 5:
            data['last_target_npc_id'] = event['npc_id']
        elif subkind == 98:
            data['challenge_notice'] = {'text_id': event['text_id'],
                                        'player_name': event['player_name'],
                                        'npc_id': event['npc_id']}
        elif subkind == 6:
            data['room'] = None
            data['members'] = []
            data['objectives'] = {}
            data['phase'] = 'idle'
        elif subkind == 100:
            data.setdefault('objectives', {})['records'] = list(event.get('records', []))
            data['completed'] = True
            data['completion_source'] = 'S85-21-100'
            data['phase'] = 'completed'
            data['status'] = '伺服器通知新式副本已完成；不自動推測獎勵'
        elif subkind in (99, 101, 102):
            data['status'] = '新式副本狀態通知：%d' % subkind
    elif kind == 'instance_reward_status':
        data['reward'] = {'reward_count': event['reward_count'],
                          'win_stage': event['win_stage'],
                          'open_reward': event['open_reward'],
                          'reward_mark': event['reward_mark'],
                          'npc_id': event['npc_id']}
        data['status'] = '協力獎勵狀態已同步（尚未領取）'
    elif kind == 'instance_fight_count':
        data['fight_count'] = event['count']
        data['fight_consumed_battle'] = None
        data['last_fight_victory'] = None
    elif kind == 'instance_standby':
        data['standby'] = event['standby']
    # Resolve only after the authoritative room event has been applied.
    from wlre.services.instance_creation import resolve as resolve_create
    from wlre.services.instance_room_flow import resolve as resolve_room
    from wlre.services.instance_standby import resolve as resolve_standby
    from wlre.services.instance_start import resolve as resolve_start
    resolve_create(state, event)
    resolve_room(state, event)
    resolve_standby(state, event)
    resolve_start(state, event)
    from wlre.services.instance_entry import observe as observe_entry
    observe_entry(state, event)
    from wlre.services.instance_rewards import resolve as resolve_rewards
    resolve_rewards(state, event)
