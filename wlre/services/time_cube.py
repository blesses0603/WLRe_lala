"""Time cube: UILoginAward.RevLotteryOLInfo / OnClick_Event_Receive.

Only S122-1 authorizes C122-2. A countdown never creates claimable cubes.
S122-2 is ignored by the official Lua; it is not a success receipt here.
"""
import time
from wlre.network.wire import Packet, Reader, ProtocolError


def defaults():
    return dict(enabled=True, ready=False, count=None, deadline=None,
                role_id=None, pending=None, uncertain=False, revision=0,
                status='等待伺服器同步時間魔方')


def decode_cube(packet):
    if packet.main != 122 or packet.sub not in (1, 2, 3):return None
    r=Reader(packet.payload)
    if packet.sub == 2:
        # The official handler intentionally ignores the obsolete award payload.
        return dict(type='cube_legacy_result')
    if packet.sub == 3:
        item_id=r.u16();r.end()
        if not item_id:raise ProtocolError('時間魔方福袋 ID 無效')
        return dict(type='cube_item',item_id=item_id)
    kind,count,check,keep=r.u8(),r.u8(),r.u16(),r.u16();r.end()
    if kind not in (0,1) or count>3:
        raise ProtocolError('時間魔方狀態格式無效')
    return dict(type='cube_info',kind=kind,count=count,check_minutes=check,keep_minutes=keep)


def apply_cube(state,event,now=None):
    now=time.monotonic() if now is None else now
    kind=event['type'];cube=state.time_cube
    if kind=='role_list_available':
        state.time_cube=defaults();return
    if kind=='world_player':
        role=event['player']['role_id']
        if cube['role_id'] not in (None,role):state.time_cube=defaults()
        state.time_cube['role_id']=role
        return
    if kind=='cube_item':cube['item_id']=event['item_id']
    elif kind=='cube_info':
        cube.update(ready=True,count=event['count'],revision=cube['revision']+1)
        cube['role_id']=state.player.get('role_id')
        if event['kind']==0:
            cube['deadline']=now+max(0,event['check_minutes']-event['keep_minutes'])*60
            cube['check_minutes']=event['check_minutes']
        pending=cube['pending']
        if pending and event['count']<pending['count']:
            pending['count_updated']=True
        if not pending and not cube['uncertain']:
            cube['status']='伺服器已同步魔方狀態'


def problem(state):
    from wlre.services.coordination import reason,active
    from wlre.services.instance_rewards import bag_claim_problem
    cube=state.time_cube
    if state.phase!='world_ready' or not state.initial_data_complete or not state.player.get('role_id'):
        return '等待角色與世界同步'
    if not cube['ready'] or cube['role_id']!=state.player.get('role_id'):return '等待伺服器同步魔方次數'
    if cube['uncertain']:return '魔方開啟結果不明，請重新登入同步'
    if cube['pending']:return '等待魔方次數與背包更新，不重複送出'
    if not cube['count']:return '分析中，等待伺服器確認可開啟次數'
    pause=reason(state,'time_cube')
    if pause:return pause
    for work in (state.maintenance,state.room_storage,state.crafting,state.alchemy,state.expedition):
        if active(work) or work.get('enabled') or work.get('auto_continue'):
            return '等待其他背包操作結束'
    if any(d.get('claim_pending') is not None or d.get('cancel_pending') is not None
           or d.get('reward_uncertain') for d in state.instances.values()):
        return '等待副本領獎確認'
    return bag_claim_problem(state.inventory,required_slots=cube['count']) or ''


def command(state,value,now=None):
    cube=state.time_cube
    if value.get('action')=='auto':
        enabled=value.get('enabled')
        if type(enabled) is not bool:raise ProtocolError('魔方自動開啟設定必須為布林值')
        cube['enabled']=enabled
        cube['status']='已啟用自動開啟' if enabled else '已關閉自動開啟'
        return []
    if value.get('action')!='open':raise ProtocolError('未知的魔方操作')
    issue=problem(state)
    if issue:raise ProtocolError(issue)
    now=time.monotonic() if now is None else now
    cube['pending']=dict(count=cube['count'],bag_revision=state.inventory['revision'],
                         count_updated=False,due=now+15)
    cube['status']='已送出開啟要求，等待伺服器次數及背包更新'
    return [Packet(122,2)]


def tick(state,world_acknowledged,now=None):
    now=time.monotonic() if now is None else now
    cube=state.time_cube;pending=cube['pending']
    if pending:
        if (pending['count_updated'] and state.inventory.get('reliable')
                and state.inventory.get('revision',0)>pending['bag_revision']):
            cube.update(pending=None,status='已收到次數及背包更新；實際獎勵以背包為準')
        elif now>=pending['due']:
            cube.update(pending=None,uncertain=True,status='魔方開啟結果不明，停止重送；請重新登入同步')
        return []
    if not world_acknowledged or not cube['enabled'] or not state.automation['enabled']:return []
    issue=problem(state)
    if issue:
        cube['status']=issue;return []
    return command(state,dict(action='open'),now)


def disconnect(state):
    cube=state.time_cube
    cube.update(enabled=False,ready=False,uncertain=bool(cube['pending']) or cube['uncertain'],
                pending=None,status='連線結束，魔方自動開啟已停止')
