"""帳篷控制：1262 Bag.lua / Stage.lua / Protocols_065.lua。

只由 S65 及進入自家帳篷後的 S62-4 更新確認狀態；不猜測操作成功，
不重送逾時指令，也不把未見到的帳篷視為已收起。
"""
import time

from wlre.core.state_ownership import writes
from wlre.network.wire import Packet, ProtocolError, Reader, Writer

TIMEOUT = 15.0
HOUSE_SCENES = frozenset((10299, 10298, 10000))  # 1262 Define.lua FurSysSceneNum


def defaults():
    return {
        'scene': None, 'scene_known': False, 'visible': False,
        'deployed_scene': None, 'tent_id': None, 'x': None, 'y': None,
        'kind': None, 'make': None, 'inside': False, 'access_open': None,
        'pending': None, 'uncertain': False, 'status': '帳篷狀態待伺服器同步',
        'interior_scene': None, 'return_scene': None, 'entry_context': None,
    }


def _camp(r):
    return {
        'owner_id': r.u32(), 'tent_id': r.u16(), 'x': r.u32(),
        'y': r.u32(), 'kind': r.u8(), 'make': r.u8(),
    }


def decode_tent(packet):
    if packet.main != 65:
        return None
    sub = packet.sub
    r = Reader(packet.payload)
    event = {'main': 65, 'sub': sub}
    if sub == 1:
        if r.remaining != 16:
            raise ProtocolError('S65-1 帳篷資料長度不符')
        event.update(type='tent_added', tent=_camp(r))
    elif sub == 3:
        if r.remaining % 16:
            raise ProtocolError('S65-3 帳篷清單長度不符')
        event.update(type='tent_scene_list', tents=[_camp(r) for _ in range(r.remaining // 16)])
    elif sub == 4:
        if r.remaining != 4:
            raise ProtocolError('S65-4 帳篷移除資料長度不符')
        event.update(type='tent_removed', owner_id=r.u32())
    elif sub == 7:
        if r.remaining != 2:
            raise ProtocolError('S65-7 帳篷開放狀態長度不符')
        event.update(type='tent_access', access_open=r.u8() == 0, show_message=bool(r.u8()))
    elif sub == 16:
        if r.remaining != 1:
            raise ProtocolError('S65-16 帳篷錯誤碼長度不符')
        event.update(type='tent_error', code=r.u8())
    elif sub == 18:
        if r.remaining != 2:
            raise ProtocolError('S65-18 帳篷外觀長度不符')
        event.update(type='tent_appearance', kind=r.u8(), make=r.u8())
    elif sub in (2, 5, 8):
        if r.remaining:
            # 尚未驗證的擴充資料不能錯認為確定的拒絕結果。
            return None
        event.update(type={2:'tent_limit', 5:'tent_owner_left', 8:'tent_entry_denied'}[sub])
    else:
        return None
    r.end()
    return event


def _visible(t, data, scene):
    t.update(scene=scene, scene_known=True, visible=True,
             deployed_scene=scene, tent_id=data['tent_id'],
             x=data['x'], y=data['y'], kind=data['kind'], make=data['make'])
    if t.get('pending') and t['pending']['action'] == 'open':
        t.update(pending=None, uncertain=False)
    t['status'] = ('等待進入自家帳篷的伺服器確認'
                   if t.get('pending') and t['pending']['action'] == 'enter'
                   else '自家帳篷已由伺服器確認展開')


def _removed(t):
    t.update(visible=False, deployed_scene=None, tent_id=None,
             x=None, y=None, inside=False, interior_scene=None, entry_context=None, pending=None,
             uncertain=False, status='伺服器已確認收起帳篷')


def _private_scene(scene):
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    runtime=current_runtime()
    return (runtime is not None and type(scene) is int and 1<=scene<=65535
            and scene not in getattr(runtime,'stages',{}))


def _confirm_enter(t, scene):
    context=t.get('entry_context') or t.get('pending')
    if (context and context.get('action')=='enter'
            and context.get('furniture_received')
            and scene!=context.get('source_scene')
            and (scene in HOUSE_SCENES or _private_scene(scene))):
        t.update(pending=None,uncertain=False,inside=True,interior_scene=scene,
                 return_scene=context.get('source_scene'),entry_context=None,
                 status='已進入自家帳篷（伺服器換圖與自家家具確認）')


def exit_door_index():
    """Use current official house-template door links, never an invented opcode."""
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    runtime=current_runtime()
    if runtime is None:raise ProtocolError('目前官方帳篷出口資料尚未就緒')
    candidates=set()
    for template in HOUSE_SCENES:
        for door in getattr(runtime,'doors',{}).get(template,()):
            index=door.get('index')
            link=getattr(runtime,'portal_destinations',{}).get((template,index),{})
            destination=link.get('destination')
            if (type(index) is int and 1<=index<=65535
                    and link.get('matched_stage_map') is True
                    and link.get('destination_verified') is True
                    and type(destination) is int and 1<=destination<=65535
                    and destination not in HOUSE_SCENES
                    and link.get('event_x')==door.get('x')
                    and link.get('event_y')==door.get('y')):
                candidates.add(index)
    if len(candidates)!=1:
        raise ProtocolError('目前官方帳篷出口索引未能唯一核對，請重新同步官方資源')
    return next(iter(candidates))


def apply_tent(state, event):
    t = state.tent
    kind = event['type']
    pid = state.player.get('role_id')
    if kind == 'world_player':
        state.tent = {**defaults(), 'scene': state.player.get('scene')}
        return
    if kind == 'position_snapshot' and event.get('role_id') == pid:
        scene = event['scene']
        if t['scene'] != scene:
            was_inside=t['inside']
            t.update(scene=scene,scene_known=False,visible=False)
            if was_inside and scene==t.get('return_scene'):
                t.update(inside=False,interior_scene=None,pending=None,uncertain=False,
                         status='已離開自家帳篷（伺服器位置確認）')
            elif was_inside and (scene in HOUSE_SCENES or _private_scene(scene)):
                t.update(inside=True,interior_scene=scene)
            else:
                t['inside']=False
                t['status']=('已切換場景，等待自家帳篷內部資料確認'
                             if t.get('entry_context') else '已切換場景，等待本場景帳篷資料')
            _confirm_enter(t,scene)
        return
    if kind == 'tent_added':
        if pid is not None and event['tent']['owner_id'] == pid:
            _visible(t, event['tent'], state.player.get('scene'))
    elif kind == 'tent_scene_list':
        t.update(scene_known=True, scene=state.player.get('scene'))
        own = next((c for c in event['tents'] if pid is not None and c['owner_id'] == pid), None)
        if own:
            _visible(t, own, t['scene'])
        else:
            t['visible'] = False
            if not t.get('pending'):
                t['status'] = ('本場景未見自家帳篷；其他場景狀態待確認'
                               if t['deployed_scene'] is not None
                               else '本場景未見自家帳篷')
    elif kind == 'tent_removed' and pid is not None and event['owner_id'] == pid:
        _removed(t)
    elif kind == 'tent_limit' and t.get('pending') and t['pending']['action'] == 'open':
        t.update(pending=None, status='伺服器拒絕：本場景帳篷已達上限')
    elif kind == 'tent_entry_denied' and t.get('pending') and t['pending']['action'] == 'enter':
        t.update(pending=None,entry_context=None,status='伺服器拒絕進入帳篷')
    elif kind == 'tent_error' and t.get('pending'):
        code = event['code']
        t.update(pending=None,entry_context=None,status=(
            '伺服器拒絕：沒有帳篷標記' if code == 2
            else f'帳篷操作未成功（伺服器錯誤碼 {code}）'))
    elif kind == 'tent_access':
        t['access_open'] = event['access_open']
    elif kind == 'tent_appearance':
        t.update(kind=event['kind'], make=event['make'])
    elif (event.get('room_action') == 'snapshot' and pid is not None
          and event.get('owner') == pid and t.get('entry_context')):
        t['entry_context']['furniture_received']=True
        _confirm_enter(t,state.player.get('scene'))
        if not t['inside']:
            t['status']='自家帳篷家具已收到，等待房屋場景確認'
    elif kind=='event_rejected' and t.get('pending') and t['pending']['action']=='leave':
        t.update(pending=None,status=event.get('reason','伺服器拒絕離開帳篷'))


@writes('tent')
def command(state, instruction, now=None):
    now = time.monotonic() if now is None else now
    action = instruction.get('action')
    if action not in ('open', 'close', 'enter', 'leave'):
        raise ProtocolError('未知帳篷操作')
    if (state.phase != 'world_ready' or not state.initial_data_complete
            or not state.player.get('role_id')):
        raise ProtocolError('請先完成角色與世界資料同步')
    t = state.tent
    if t['pending']:
        raise ProtocolError('帳篷操作等待伺服器確認，請勿重複送出')
    if t['uncertain']:
        raise ProtocolError('帳篷操作結果不明，請重新登入同步後再操作')
    if state.battle.get('active') or state.event_flow.get('blocked'):
        raise ProtocolError('請先結束戰鬥或事件，再操作帳篷')
    if state.local_movement and state.local_movement.get('status') in ('running', 'waiting'):
        raise ProtocolError('角色移動中，請等待位置確認')
    if state.roaming.get('enabled'):
        raise ProtocolError('請先停止自動徘徊，再操作帳篷')
    if state.activities:
        raise ProtocolError('請先結束目前活動，再操作帳篷')
    if action == 'open':
        if t['deployed_scene'] is not None:
            raise ProtocolError('已有展開帳篷紀錄；請確認是否需收起，或重新登入同步')
        if t['inside'] or state.player.get('scene') in HOUSE_SCENES:
            raise ProtocolError('在小屋內不能展開帳篷')
        packet = Packet(65, 6)
        label = '展開'
    elif action == 'close':
        if t['deployed_scene'] is None:
            raise ProtocolError('尚未收到自家帳篷展開證據，不能直接收起')
        if t['inside'] or state.player.get('scene') in HOUSE_SCENES:
            raise ProtocolError('在自己的小屋內不能收起帳篷')
        packet = Packet(65, 2)
        label = '收起'
    elif action=='leave':
        if not t['inside'] or t.get('interior_scene')!=state.player.get('scene'):
            raise ProtocolError('目前尚未確認位於自家帳篷內')
        packet=Packet(20,8,Writer().u16(exit_door_index()).build())
        label='離開'
    else:
        if not t['visible'] or t['scene'] != state.player.get('scene'):
            raise ProtocolError('目前場景尚未確認自家帳篷，請先展開或移至帳篷所在場景')
        packet = Packet(65, 1, Writer().u32(state.player['role_id']).build())
        label = '進入'
    if action=='enter':
        t['entry_context']={'action':'enter','source_scene':state.player.get('scene'),
                            'furniture_received':False}
    t.update(pending={'action': action, 'due': now + TIMEOUT},
             status=f'已要求{label}帳篷，等待伺服器確認')
    return [packet]


@writes('tent')
def expire(state, now=None):
    now = time.monotonic() if now is None else now
    t = state.tent
    if not t['pending'] or now < t['pending']['due']:
        return False
    t.update(pending=None, uncertain=True,
             status='帳篷操作逾時，結果未確認；不會自動重送，請重新登入同步')
    return True


def activity_text(t):
    if not t:
        return '帳篷｜尚未收到資料'
    if t.get('uncertain') or t.get('pending'):
        return '帳篷｜' + t.get('status', '等待回覆')
    if t.get('inside'):
        return '帳篷｜已進入自家帳篷'
    if t.get('visible'):
        return f"帳篷｜已展開（{t.get('x')}、{t.get('y')}）"
    if t.get('deployed_scene') is not None:
        return '帳篷｜曾在其他場景展開，現況待確認'
    if t.get('scene_known'):
        return '帳篷｜目前場景未見自家帳篷'
    return '帳篷｜本場景狀態待同步'
