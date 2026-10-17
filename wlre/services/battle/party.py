"""Manual party requests and server-confirmed membership. No automatic accepts."""
import time
from wlre.network.wire import Packet, Writer, ProtocolError

ERRORS={5:'釣魚中無法組隊',6:'採集中無法組隊',8:'對方忙碌',10:'對方未開啟組隊邀請',15:'對方已離線',16:'不在相同地圖',17:'對方戰鬥中',19:'對方忙碌',20:'對方已有隊伍',21:'對方已有隊伍',22:'隊伍已滿',24:'請先解除騎乘',27:'配對中無法變更隊伍',28:'對方配對中',30:'二轉條件不符'}


def party_defaults():return {'teams':{},'nearby':{},'requests':{},'outbound':{},'enabled':None,'status':'尚無隊伍資料'}
def own_team(state):
    data=state if isinstance(state,dict) else state.__dict__
    pid=data.get('player',{}).get('role_id')
    return next((t for t in data.get('party',{}).get('teams',{}).values() if pid in t['members']),None)
def player_name(data,rid):
    if rid==data.get('player',{}).get('role_id'):return data['player'].get('name',str(rid))
    return data.get('party',{}).get('nearby',{}).get(str(rid),{}).get('name',str(rid))


def apply_party(state,event):
    p=state.party;k=event['type'];rid=event.get('role_id');now=time.monotonic()
    if k=='nearby_player':p['nearby'][str(event['player']['role_id'])]=dict(event['player'])
    elif k=='nearby_leave':p['nearby'].pop(str(rid),None)
    elif k=='position_snapshot':
        if rid==state.player.get('role_id'):
            scene=event['scene'];p['nearby']={key:v for key,v in p['nearby'].items() if v.get('scene')==scene}
        elif str(rid) in p['nearby']:p['nearby'][str(rid)].update(scene=event['scene'],x=event['x'],y=event['y'])
    elif k in ('team_invite','team_application','team_leader_offer'):
        key=f'{k}:{rid}'
        p['requests'][key]={'key':key,'type':k,'role_id':rid,'expires':now+60,'status':'pending'}
        p['status']='收到組隊請求，請選擇接受或拒絕'
    elif k=='team_list':
        for team in event['teams']:p['teams'][str(team['leader_id'])]=dict(team)
        p['status']='隊伍名單已更新（伺服器確認）'
    elif k=='team_join':
        leader=event['leader_id'];team=p['teams'].setdefault(str(leader),{'leader_id':leader,'members':[leader]})
        if rid not in team['members']:team['members'].append(rid)
        p['outbound'].clear();p['status']='組隊成功（伺服器確認）'
        if state.player.get('role_id') in team['members']:
            p['requests']={key:v for key,v in p['requests'].items() if v['type']!='team_invite' and v['role_id']!=rid}
    elif k=='team_leave':
        for key,team in list(p['teams'].items()):
            if rid in team['members']:
                if rid==team['leader_id'] or len(team['members'])<=2:p['teams'].pop(key)
                else:team['members'].remove(rid)
        p['outbound'].clear();p['status']='離隊／解散已由伺服器確認'
    elif k=='team_new_leader':
        old=str(event['old_leader_id']);leader=event['leader_id'];team=p['teams'].pop(old,None)
        if team:
            team['leader_id']=leader;team['members']=[leader]+[v for v in team['members'] if v!=leader];p['teams'][str(leader)]=team
        p['outbound'].clear();p['requests']={key:v for key,v in p['requests'].items() if v['type']!='team_leader_offer'}
        p['status']='隊長已變更（伺服器確認）'
    elif k=='team_flag':
        p['enabled']=event['enabled'];p.pop('enabled_requested',None);p['status']='組隊開關：'+('開啟' if event['enabled'] else '關閉')
    elif k in ('team_answer','team_leader_answer'):
        answer=event['answer'];p['status']={1:'對方同意，等待隊伍名單',2:'對方拒絕',3:'對方忙碌／未回應'}.get(answer,f'組隊回覆 {answer}')
        if rid:
            p['outbound']={key:v for key,v in p['outbound'].items() if v['role_id']!=rid}
        else:p['outbound'].clear()
    elif k=='team_notice':p['status']={1:'邀請已送達，等待對方確認',2:'申請已送達，等待隊長確認'}.get(event['code'],f'組隊通知 {event["code"]}')
    elif k=='social_rejected':p['status']=ERRORS.get(event['code'],f'伺服器拒絕操作（代碼{event["code"]}）');p['outbound'].clear()


def expire(state,now=None):
    now=time.monotonic() if now is None else now;p=state.party;changed=False
    for collection in ('requests','outbound'):
        for key,request in list(p[collection].items()):
            if now>=request['expires']:
                p[collection].pop(key);p['status']='組隊請求已逾時，請重新確認';changed=True
    return changed


def team_command(command,state,now=None):
    now=time.monotonic() if now is None else now;expire(state,now)
    action=command['action'];p=state.party;pid=state.player.get('role_id');team=own_team(state)
    if action=='flag':
        enabled=bool(command.get('enabled'));p['enabled_requested']=enabled;p['status']='組隊開關已送出，等待伺服器同步'
        return [Packet(33,5,bytes([1 if enabled else 2]))]
    if action=='respond':
        key=command.get('request');request=p['requests'].get(key)
        if not request or request['status']!='pending':raise ProtocolError('此請求已回覆或逾時')
        answer=int(command['answer'])
        if answer not in (1,2):raise ProtocolError('回覆必須為接受或拒絕')
        if answer==1:
            if state.battle.get('active') or state.event_flow.get('blocked') or state.alchemy.get('enabled') or state.alchemy.get('pending'):raise ProtocolError('請先結束戰鬥、事件或煉金後再接受')
            if request['type']=='team_invite' and team:raise ProtocolError('已有隊伍，不能接受其他邀請')
            if request['type']=='team_application' and team and team['leader_id']!=pid:raise ProtocolError('只有隊長可以接受入隊申請')
            if request['type']=='team_application' and team and len(team['members'])>=4:raise ProtocolError('隊伍已滿')
        sub={'team_invite':8,'team_application':3,'team_leader_offer':10}[request['type']]
        body=(bytes([3]) if answer==1 else bytes([2,2])) if sub==10 else Writer().u8(answer).u32(request['role_id']).build()
        if answer==2:
            p['requests'].pop(key);p['status']='拒絕回覆已送出'
        else:
            request.update(status='sent',expires=now+15);p['status']='接受回覆已送出，等待伺服器確認'
        return [Packet(13,sub,body)]
    if state.battle.get('active') or state.event_flow.get('blocked'):raise ProtocolError('目前戰鬥／事件中，請稍後組隊')
    if action=='leave':
        if not team:raise ProtocolError('目前沒有隊伍')
        rid=pid;sub=4;body=b''
    else:
        rid=int(command.get('role_id',0))
        if not 0<rid<=0xffffffff or rid==pid:raise ProtocolError('請選擇其他玩家的有效角色ID')
        if action in ('invite','apply'):
            target=p['nearby'].get(str(rid))
            if target and target.get('scene')!=state.player.get('scene'):raise ProtocolError('目標不在相同地圖')
            if p.get('enabled_requested',p['enabled']) is False:raise ProtocolError('請先開啟組隊開關')
            if action=='apply' and team:raise ProtocolError('已有隊伍，請先離隊')
            if action=='invite' and team and (team['leader_id']!=pid or len(team['members'])>=4):raise ProtocolError('只有未滿隊的隊長可邀請')
            sub=7 if action=='invite' else 1;body=Writer().u32(rid).build()
        elif action in ('kick','leader'):
            if not team or team['leader_id']!=pid or rid not in team['members']:raise ProtocolError('僅隊長可操作目前隊員')
            sub=9 if action=='kick' else 10;body=(b'\x01' if sub==10 else b'')+Writer().u32(rid).build()
        else:raise ProtocolError('未知組隊操作')
    key=f'{action}:{rid}'
    if key in p['outbound']:raise ProtocolError('請求已送出，請等待回覆')
    p['outbound'][key]={'role_id':rid,'expires':now+15};p['status']='請求已送出，等待伺服器回覆'
    return [Packet(13,sub,body)]


def event_text(event):
    kind=event['type'];rid=event.get('role_id','')
    if kind in ('team_invite','team_application','team_leader_offer'):
        label={'team_invite':'組隊邀請','team_application':'入隊申請','team_leader_offer':'隊長交接確認'}[kind]
        return f'收到{label}（角色ID {rid}），請到組隊頁接受／拒絕'
    if kind=='team_join':return f"伺服器確認：角色 {rid} 加入隊長 {event['leader_id']} 的隊伍"
    if kind=='team_leave':return f'伺服器確認：角色 {rid} 已離隊'
    if kind=='team_new_leader':return f"伺服器確認：新隊長 {event['leader_id']}"
    if kind=='team_list':return '伺服器隊伍名單已同步'
    if kind=='team_flag':return '伺服器組隊開關：'+('開啟' if event['enabled'] else '關閉')
    if kind=='social_rejected':return ERRORS.get(event['code'],f"伺服器拒絕操作（代碼 {event['code']}）")
    if kind in ('team_answer','team_leader_answer'):return f"角色 {rid} 回覆："+{1:'同意，等待隊伍通知',2:'拒絕',3:'忙碌／未回應'}.get(event['answer'],str(event['answer']))
    if kind=='team_notice':return {1:'邀請已送達，等待對方確認',2:'申請已送達，等待隊長確認'}.get(event['code'],f"組隊通知 {event['code']}")
    return kind
