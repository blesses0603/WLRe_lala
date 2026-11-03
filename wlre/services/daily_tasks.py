"""Server-authoritative daily/weekly tasks using the current verified runtime.

Lua evidence: Logic/Activity.lua DailyTask, Protocols/Protocols_124.lua.
The game owns task progress and reset timing. This module never invents a
completion, triggers a paid condition, or sends packets without known data.
"""
import time
from wlre.network.wire import Packet, ProtocolError, Reader, Writer


TASK_ERRORS = {
    1: "條件未完成", 2: "超過群組數量", 3: "索引超過",
    4: "無任務資料", 5: "設定標記失敗", 6: "檢查給獎失敗",
    7: "給獎失敗", 8: "已領取", 9: "無條件種類",
    10: "不在活動期間", 11: "積分不足", 12: "付費獎勵未授權",
    13: "獎勵資料種類無效", 14: "獎勵資料數量為零",
    15: "背包空間不足",
}


def defaults():
    return {
        "enabled": True, "pending": None, "uncertain": False, "handled": [],
        "role_id": None, "generation": 0, "revision": 0, "catalog_token": None,
        "catalog_ready": False, "rows": [], "chests": [], "groups_ahead": False, "awaiting_groups": False,
        "status": "等待每日／每週任務同步",
        "ready": False,
        "groups_ready": False,
        "daily_group": None,
        "weekly_group": None,
        "daily_value": None,
        "weekly_value": None,
        "daily_progress": [],
        "weekly_progress": [],
        "daily_done_mark": 0,
        "daily_reward_mark": 0,
        "daily_event_reward_a": 0,
        "daily_event_reward_b": 0,
        "weekly_done_mark": [],
        "weekly_reward_mark": 0,
        "weekly_event_reward_a": 0,
        "weekly_event_reward_b": 0,
        "daily_event_active": False,
        "weekly_event_active": False,
        "last_notice": "",
    }


def _read_marks(reader):
    result = {
        "daily_value": reader.u8(),
        "weekly_value": reader.u8(),
        "daily_done_mark": reader.u8(),
        "daily_reward_mark": reader.u8(),
        "daily_event_reward_a": reader.u8(),
        "daily_event_reward_b": reader.u8(),
        "weekly_done_mark": [reader.u8(), reader.u8()],
        "weekly_reward_mark": reader.u8(),
        "weekly_event_reward_a": reader.u8(),
        "weekly_event_reward_b": reader.u8(),
    }
    return result


def decode_daily_tasks(packet):
    """S124-1/2/3 are exact layouts; reward bodies are intentionally opaque."""
    if packet.main != 124 or packet.sub not in (1, 2, 3, 4, 5):
        return None
    reader = Reader(packet.payload)
    if packet.sub == 1:
        daily_value = reader.u8()
        weekly_value = reader.u8()
        daily_progress = [reader.u8() for _ in range(8)]
        weekly_progress = [reader.u8() for _ in range(12)]
        marks = {
            "daily_value": daily_value,
            "weekly_value": weekly_value,
            "daily_progress": daily_progress,
            "weekly_progress": weekly_progress,
            "daily_done_mark": reader.u8(),
            "daily_reward_mark": reader.u8(),
            "daily_event_reward_a": reader.u8(),
            "daily_event_reward_b": reader.u8(),
            "weekly_done_mark": [reader.u8(), reader.u8()],
            "weekly_reward_mark": reader.u8(),
            "weekly_event_reward_a": reader.u8(),
            "weekly_event_reward_b": reader.u8(),
            "daily_event_active": bool(reader.u8()),
            "weekly_event_active": bool(reader.u8()),
        }
        reader.end()
        if packet.payload[-2] not in (0,1) or packet.payload[-1] not in (0,1):
            raise ProtocolError('每日任務活動旗標無效')
        return {"type": "daily_task_snapshot", **marks}
    if packet.sub == 2:
        groups = {"daily_group": reader.u8(), "weekly_group": reader.u8()}
        reader.end()
        return {"type": "daily_task_groups", **groups}
    if packet.sub == 3:
        change = reader.u8()
        if change == 1:
            marks = _read_marks(reader)
            reader.end()
            return {"type": "daily_task_marks", **marks}
        if change == 2:
            count, task_id, cycle = reader.u8(), reader.u8(), reader.u8()
            reader.end()
            if cycle not in (1,2) or not 1<=task_id<=(8 if cycle==1 else 12):
                raise ProtocolError('每日任務進度種類或格位無效')
            return {
                "type": "daily_task_progress",
                "cycle": cycle,
                "task_id": task_id,
                "count": count,
            }
        reader.take(reader.remaining)
        return {"type": "daily_task_unknown_update", "kind": change}
    if packet.sub == 4:
        kind=reader.u8()
        if kind not in (1,2):
            reader.take(reader.remaining)
            return dict(type='daily_task_reward_notice',kind=kind,awards=[])
        tail=9 if kind==2 else 0
        if reader.remaining<tail or (reader.remaining-tail)%9:
            raise ProtocolError('每日任務獎勵封包長度無效')
        awards=[dict(kind=reader.u8(),id=reader.u32(),value=reader.u32())
                for _ in range((reader.remaining-tail)//9)]
        reader.take(tail);reader.end()
        return dict(type='daily_task_reward_notice',kind=kind,awards=awards)
    code = reader.u8()
    reader.end()
    return {"type": "daily_task_error", "code": code,
            "message": TASK_ERRORS.get(code, "未知每日任務錯誤")}


def apply_daily_tasks(state,event):
    data=state.daily_tasks;kind=event['type']
    if kind=='role_list_available':state.daily_tasks=defaults();return
    if kind=='world_player':
        role=event['player']['role_id']
        if data['role_id'] not in (None,role):state.daily_tasks=defaults()
        state.daily_tasks['role_id']=role
        return
    if not kind.startswith('daily_task_'):return
    data['revision']+=1
    if kind=='daily_task_snapshot':
        if data['ready']:
            if data['pending']:data['uncertain']=True
            data['pending']=None;data['handled']=[];data['generation']+=1
        data['groups_ready']=data['groups_ahead']
        data['awaiting_groups']=not data['groups_ahead']
        data.update({k:v for k,v in event.items() if k!='type'})
        data.update(ready=True,groups_ahead=False,status='每日／每週進度已由伺服器同步')
    elif kind=='daily_task_groups':
        changed=(data['daily_group'] is not None and
                 (data['daily_group'],data['weekly_group'])!=(event['daily_group'],event['weekly_group']))
        snapshot_fresh=data['ready'] and data['awaiting_groups']
        if not snapshot_fresh and (changed or data['ready']):
            if data['pending']:data['uncertain']=True
            data.update(ready=False,pending=None,handled=[],generation=data['generation']+1)
        data.update(daily_group=event['daily_group'],weekly_group=event['weekly_group'],
                    groups_ready=True,groups_ahead=not snapshot_fresh,awaiting_groups=False)
    elif kind=='daily_task_marks' and data['ready']:
        regressed=any(old & ~new for old,new in (
            (data['daily_done_mark'],event['daily_done_mark']),
            (sum(x<<(8*i) for i,x in enumerate(data['weekly_done_mark'])),
             sum(x<<(8*i) for i,x in enumerate(event['weekly_done_mark']))),
            (data['daily_reward_mark'],event['daily_reward_mark']),
            (data['weekly_reward_mark'],event['weekly_reward_mark']),
            (data['daily_event_reward_a'],event['daily_event_reward_a']),
            (data['weekly_event_reward_a'],event['weekly_event_reward_a'])))
        if regressed or event['daily_value']<data['daily_value'] or event['weekly_value']<data['weekly_value']:
            if data['pending']:data['uncertain']=True
            data.update(ready=False,groups_ready=False,pending=None,handled=[],generation=data['generation']+1,
                        status='任務週期已變動，等待完整快照與群組同步')
        data.update({k:v for k,v in event.items() if k!='type'})
    elif kind=='daily_task_progress' and data['ready']:
        key='daily_progress' if event['cycle']==1 else 'weekly_progress'
        if event['count']<data[key][event['task_id']-1]:
            if data['pending']:data['uncertain']=True
            data.update(ready=False,groups_ready=False,pending=None,status='進度已重置，等待完整任務同步')
        else:data[key][event['task_id']-1]=event['count']
    elif kind=='daily_task_error':
        data.update(enabled=False,pending=None,status='伺服器拒絕，已停止自動領獎：'+event['message'])
    elif kind=='daily_task_reward_notice':
        pending=data['pending']
        if pending and event['kind']==(1 if pending['kind']=='task' else 2):
            pending['notice']=True
    elif kind=='daily_task_unknown_update':
        if data['pending']:data['uncertain']=True
        data.update(ready=False,pending=None,status='未知的任務更新格式，等待重新登入同步')


def _has_flag(flag, task_id):
    """Lua CheckFlag/CheckFlags are one-indexed little-endian bitsets."""
    if type(task_id) is not int or task_id < 1:
        return False
    if isinstance(flag, list):
        if task_id > 8 * len(flag):
            return False
        flag = flag[(task_id - 1) // 8]
    elif task_id > 8:
        return False
    return bool(flag & (1 << ((task_id - 1) % 8)))




CONDITIONS={1:'登入',2:'回收',3:'家具佈置',4:'聊天',5:'拍照',6:'生活技能',7:'煉金',
            8:'製作',9:'方舟',10:'組織',11:'日常任務',12:'副本',13:'活動',14:'對戰',
            15:'經驗',16:'時間魔方',17:'裝備加工',18:'商城',19:'交易所',20:'儲值'}


def runtime_catalog():
    from wlre.services.world.dynamic_bundle_runtime import current_runtime,current_catalog_token
    token=current_catalog_token();runtime=current_runtime()
    catalog=getattr(runtime,'daily_tasks',None)
    if token!=current_catalog_token() or not getattr(runtime,'catalog_identity',None) or not catalog:
        return None,token,getattr(runtime,'daily_task_status','等待官方每日任務 Runtime')
    return catalog,token,'同版官方任務與寶箱資料已載入'


def received(data,row):
    return _has_flag(data['daily_done_mark'] if row['cycle']==1 else data['weekly_done_mark'],row['id'])


def chest_received(data,row):
    key=('daily_' if row['kind'] in (1,2) else 'weekly_')
    key+='event_reward_a' if row['kind'] in (2,4) else 'reward_mark'
    return _has_flag(data[key],row['mark'])


def task_rows(data,catalog):
    rows=[]
    for task in catalog['tasks']:
        cycle=task['cycle'];prefix='daily_' if cycle==1 else 'weekly_'
        if task['group']!=data[prefix+'group']:continue
        counts=data[prefix+'progress'];n=task['id']
        count=counts[n-1] if data['ready'] and n<=len(counts) else None
        claimed=received(data,task)
        eligible=(data['ready'] and data['groups_ready'] and type(task['goal']) is int
                  and task['goal']>0 and count is not None and count>=task['goal'] and not claimed)
        rows.append({**task,'progress':count,'received':claimed,'eligible':eligible,
                     'condition':CONDITIONS.get(task['condition_kind'],'未知條件'),
                     'execution':('既有魔方自動流程' if task['condition_kind']==16 else
                                  '伺服器記錄登入' if task['condition_kind']==1 else
                                  '依指定的煉金／製作目標接續' if task['condition_kind'] in (7,8) else
                                  '副本／協力需手動開始' if task['condition_kind']==12 else '需使用者執行條件')})
    return sorted(rows,key=lambda r:(r['cycle'],not r['eligible'],r['id']))


def chest_rows(data,catalog):
    rows=[]
    for row in catalog['rewards']:
        cycle=1 if row['kind'] in (1,2) else 2;prefix='daily_' if cycle==1 else 'weekly_'
        if row['kind'] in (2,4) and not data[prefix+'event_active']:continue
        claimed=chest_received(data,row)
        eligible=(data['ready'] and data['groups_ready'] and data[prefix+'value']>=row['value'] and not claimed)
        rows.append({**row,'cycle':cycle,'received':claimed,'eligible':eligible})
    return sorted(rows,key=lambda r:(r['cycle'],r['kind'],r['value']))


def slots_needed(awards):
    needed=0;seen=False
    for award in awards:
        if not award['kind']:continue
        seen=True
        if not award['value']:raise ProtocolError('獎勵數量無效')
        if award['kind'] in (10,11):
            # Do not infer stackability from historical item tables.
            needed+=award['value']
        elif award['kind'] not in (1,2,6,12,28,29,30,31):
            raise ProtocolError('獎勵含未支援種類／隨機福袋，無法確認背包空間')
    if not seen:raise ProtocolError('沒有可驗證的獎勵')
    return needed


def candidates(data,catalog):
    result=[]
    for row in task_rows(data,catalog):
        if row['eligible']:
            result.append(dict(kind='task',cycle=row['cycle'],index=row['index'],id=row['id'],
                               flags=[],awards=row['awards']))
    chests=chest_rows(data,catalog)
    for cycle in (1,2):
        rows=[r for r in chests if r['cycle']==cycle and r['eligible']]
        if rows:result.append(dict(kind='chest',cycle=cycle,index=None,id=None,
                        flags=[(r['kind'],r['mark']) for r in rows],
                        awards=[a for r in rows for a in r['awards']]))
    return result


def fingerprint(data,candidate,token):
    return (data['generation'],data['daily_group'],data['weekly_group'],token,
            candidate['kind'],candidate['cycle'],candidate['index'],tuple(candidate['flags']))


def guard(state):
    from wlre.services.coordination import reason,active
    d=state.daily_tasks
    if state.phase!='world_ready' or not state.initial_data_complete or not state.player.get('role_id'):
        return '等待角色與世界同步'
    if d['role_id']!=state.player.get('role_id') or not d['ready'] or not d['groups_ready']:
        return '等待完整每日／每週進度與當期群組同步'
    if d['uncertain']:return '任務領取結果不明，請重新登入同步'
    if d['pending']:return '等待任務標記、獎勵與背包確認'
    issue=reason(state,'daily_tasks')
    if issue:return issue
    for service in (state.time_cube,state.room_storage,state.maintenance,state.expedition,state.alchemy,state.crafting):
        if (active(service) or (service is not state.time_cube and service.get('enabled'))
                or service.get('auto_continue') or service.get('checking')):
            return '等待其他背包操作結束'
    for room in state.instances.values():
        if room.get('claim_pending') is not None or room.get('cancel_pending') is not None or room.get('reward_uncertain'):
            return '等待副本獎勵確認'
    return ''


def begin(state,candidate,token,now):
    from wlre.services.instance_rewards import bag_claim_problem
    issue=guard(state)
    if issue:raise ProtocolError(issue)
    d=state.daily_tasks;key=fingerprint(d,candidate,token)
    if key in d['handled']:raise ProtocolError('本項已要求領取，等待新的伺服器任務狀態')
    slots=slots_needed(candidate['awards'])
    issue=bag_claim_problem(state.inventory,required_slots=slots)
    if issue:raise ProtocolError(issue)
    d['handled'].append(key)
    d['pending']={**candidate,'token':token,'role':state.player['role_id'],'generation':d['generation'],
                  'due':now+20,'notice':False,'slots':slots,'bag_revision':state.inventory['revision']}
    d['status']='已要求領取任務獎勵' if candidate['kind']=='task' else '已要求領取活躍寶箱'
    if candidate['kind']=='task':return [Packet(124,1,Writer().u16(candidate['index']).build())]
    return [Packet(124,2,Writer().u8(candidate['cycle']).build())]


def command(state,value,world_acknowledged,now=None):
    now=time.monotonic() if now is None else now
    d=state.daily_tasks
    if value.get('action')=='auto':
        if type(value.get('enabled')) is not bool:raise ProtocolError('每日任務自動設定必須是布林值')
        d['enabled']=value['enabled'];d['status']='已啟用自動領獎' if d['enabled'] else '已暫停每日任務自動領獎'
        return []
    if not world_acknowledged:raise ProtocolError('等待世界初始化確認')
    catalog,token,note=runtime_catalog()
    if not catalog:raise ProtocolError(note)
    if d['catalog_token']!=token:raise ProtocolError('等待同版任務資料同步')
    eligible=candidates(d,catalog)
    action=value.get('action')
    if action=='task':
        index=value.get('index')
        if type(index) is not int or not 1<=index<=65535:raise ProtocolError('任務索引無效')
        eligible=[c for c in eligible if c['kind']=='task' and c['index']==index]
    elif action=='chest':
        cycle=value.get('cycle')
        if type(cycle) is not int or cycle not in (1,2):raise ProtocolError('任務週期無效')
        eligible=[c for c in eligible if c['kind']=='chest' and c['cycle']==cycle]
    elif action!='claim_ready':raise ProtocolError('未知的每日任務操作')
    if not eligible:raise ProtocolError('目前沒有伺服器確認已達標且未領取的項目')
    return begin(state,eligible[0],token,now)


def tick(state,world_acknowledged,now=None):
    now=time.monotonic() if now is None else now
    d=state.daily_tasks;catalog,token,note=runtime_catalog();p=d['pending']
    if p:
        if p['role']!=state.player.get('role_id') or p['token']!=token or p['generation']!=d['generation']:
            d.update(pending=None,uncertain=True,status='角色／官方版本／任務週期變動，停止重送')
        else:
            marked=(received(d,p) if p['kind']=='task' else
                    all(chest_received(d,dict(kind=k,mark=m)) for k,m in p['flags']))
            bag_ok=not p['slots'] or (state.inventory.get('reliable') and state.inventory.get('revision',0)>p['bag_revision'])
            if marked and p['notice'] and bag_ok:
                d.update(pending=None,status='伺服器已確認領取標記與獎勵通知')
            elif now>=p['due']:
                d.update(pending=None,uncertain=True,status='每日任務領獎逾時，結果不明；請重新登入同步')
        return []
    if d['catalog_token'] is not None and d['catalog_token']!=token:
        d.update(ready=False,groups_ready=False,handled=[],status='官方任務資料版本變動，等待重新同步')
    d.update(catalog_token=token,catalog_ready=bool(catalog))
    if not catalog:
        d.update(rows=[],chests=[],status=note);return []
    d['rows']=task_rows(d,catalog);d['chests']=chest_rows(d,catalog)
    if not world_acknowledged or not d['enabled'] or not state.automation['enabled']:return []
    issue=guard(state)
    if issue:d['status']=issue;return []
    errors=[]
    for candidate in candidates(d,catalog):
        if fingerprint(d,candidate,token) in d['handled']:continue
        try:return begin(state,candidate,token,now)
        except ProtocolError as exc:errors.append(str(exc))
    d['status']=errors[0] if errors else '等待任務進度；已達標項目會自動領獎'
    return []


def disconnect(state):
    d=state.daily_tasks
    d.update(enabled=False,ready=False,groups_ready=False,
             uncertain=d['uncertain'] or bool(d['pending']),pending=None,status='連線結束，每日任務自動領獎已停止')
