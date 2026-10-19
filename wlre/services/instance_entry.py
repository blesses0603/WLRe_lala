"""Manual C85-9 dungeon entry and authoritative battle state observations.

The client never infers entry success from sending C85-9. Official Lua 1262
has no separate S85-9 success acknowledgement, so own S7-1/S12-1 location
in the verified dungeon scene is the confirmation. Co-op is server-driven.
"""
import time
from wlre.network.wire import Packet, ProtocolError
from wlre.services.instance_browser import entries_for
from wlre.services.instance_room_flow import _activity_guard

ENTRY_TIMEOUT = 45.0
OPERATIONS = ('create', 'join', 'leave', 'standby', 'start', 'enter', 'claim', 'cancel')


def _no_unresolved_operations(state):
    for data in state.instances.values():
        if data.get('reward_uncertain'):
            raise ProtocolError('協力領獎結果不明，暫停其他副本操作')
        for operation in OPERATIONS:
            if data.get(operation + '_pending') is not None:
                raise ProtocolError('副本操作正在等待伺服器，禁止重複操作')
            if data.get(operation + '_uncertain'):
                raise ProtocolError('前次副本操作結果不明，請重新登入同步')


def enter(state, command, now=None):
    """Request ONE C85-9 after S85-5 kind=3, never for co-op."""
    if command.get('mode') != 'main':
        raise ProtocolError('協力戰鬥由伺服器配對，沒有獨立入場指令')
    _activity_guard(state, False)
    _no_unresolved_operations(state)
    if state.instances['coop'].get('room') is not None:
        raise ProtocolError('目前已有協力房間')
    main = state.instances['main']
    room_id = (main.get('room') or {}).get('room_id')
    if main.get('phase') != 'started' or type(room_id) is not int:
        raise ProtocolError('尚未收到一般副本開始確認')
    if not 1 <= room_id <= 65535 or not any(
            row['kind'] == 1 and row['map_id'] == room_id
            for row in entries_for('main')):
        raise ProtocolError('不是已驗證的一般副本房間')
    if not any(member.get('role_id') == state.player.get('role_id')
               for member in main.get('members') or ()):
        raise ProtocolError('伺服器房間名單尚未確認本角色')
    scene = state.player.get('scene')
    if type(scene) is not int or scene <= 0:
        raise ProtocolError('本角色場景尚未同步')
    if scene == room_id:
        raise ProtocolError('角色已在副本地圖，不需再次傳送')
    now = time.monotonic() if now is None else now
    main['enter_pending'] = {'room_id': room_id, 'from_scene': scene, 'started': now}
    main['enter_result'] = None
    main['status'] = '入場指令已送出，等待本角色伺服器場景確認，不自動重送'
    return [Packet(85, 9)]


def observe(state, event):
    """Server evidence only; battle completion never implies a reward."""
    kind = event.get('type')
    main, coop = state.instances['main'], state.instances['coop']
    if kind == 'instance_phase' and event.get('mode') == 'main' and event.get('kind') in (2, 4):
        if main.get('enter_pending') is not None:
            main['enter_pending'] = None
            main['enter_uncertain'] = True
            main['status'] = '入場期間房間結束，結果不明，禁止重送'
        main['entered_scene'] = None
        main['battle_active'] = False
        return
    if kind == 'instance_phase' and event.get('mode') == 'coop' and event.get('kind') == 2:
        coop['battle_active'] = False
        coop['match_kind'] = None
        return
    scene = None
    if kind == 'position_snapshot' and event.get('role_id') == state.player.get('role_id'):
        scene = event.get('scene')
    elif kind == 'world_player':
        player = event.get('player') or {}
        if player.get('role_id') == state.player.get('role_id'):
            scene = player.get('scene')
    room_id = (main.get('room') or {}).get('room_id')
    if (scene is not None and main.get('phase') in ('started', 'entered', 'combat')
            and type(room_id) is int and scene == room_id
            and any(row['kind'] == 1 and row['map_id'] == room_id
                    for row in entries_for('main'))):
        main['enter_pending'] = None
        main['enter_uncertain'] = False
        main['enter_result'] = 'confirmed'
        main['entered_scene'] = scene
        if main.get('phase') != 'combat':
            main['phase'] = 'entered'
            main['status'] = '伺服器已確認本角色進入副本場景，等待戰鬥'
        return
    if kind == 'instance_coop_match':
        if (coop.get('room') is not None and main.get('room') is None
                and (coop.get('standby') is True
                     or (coop.get('standby_pending') or {}).get('target') is True)):
            coop['phase'] = 'matched'
            coop['match_kind'] = event['kind']
            coop['status'] = '協力配對成功通知已收到，等待正式戰鬥開始'
    elif kind == 'battle_start':
        if main.get('phase') in ('entered', 'combat') and main.get('entered_scene') == room_id:
            main['phase'] = 'combat'
            main['battle_active'] = True
            main['status'] = '收到正式戰鬥開始封包，沿用既有戰鬥系統'
        if coop.get('phase') in ('matched', 'combat') and coop.get('room') is not None:
            coop['phase'] = 'combat'
            coop['battle_active'] = True
            coop['status'] = '協力配對後收到正式戰鬥開始封包'
    elif kind in ('fight_exit', 'winner'):
        if kind == 'fight_exit' and event.get('role_id') != state.player.get('role_id'):
            return
        if main.get('battle_active'):
            main['battle_active'] = False
            if main.get('phase') == 'combat':
                main['phase'] = 'entered'
                main['status'] = '戰鬥已結束；正式通關仍待 S85-15'
        if coop.get('battle_active'):
            coop['battle_active'] = False
            if coop.get('phase') == 'combat':
                coop['phase'] = 'matched'
                coop['status'] = '協力戰鬥已結束；後續場次與獎勵待伺服器確認'


def expire(state, now=None):
    main = state.instances['main']
    pending = main.get('enter_pending')
    now = time.monotonic() if now is None else now
    if pending is None or now < pending['started'] + ENTRY_TIMEOUT:
        return False
    main['enter_pending'] = None
    main['enter_uncertain'] = True
    main['status'] = '入場超時，結果不明；不可盲目重送，請同步伺服器狀態'
    return True


def disconnect(state):
    main = state.instances['main']
    if main.get('enter_pending') is not None:
        main['enter_pending'] = None
        main['enter_uncertain'] = True
        main['status'] = '進入副本期間斷線，結果不明；請重新登入同步'
