"""Guild sign-in and sequential, current-catalog gold-only donations."""
import time
from wlre.network.wire import Packet,Reader,Writer,ProtocolError


def defaults():
    return dict(sign_enabled=True,donate_enabled=True,sell_id=8,target=3,budget=450,settings_revision=0,
                reserved=0,confirmed=0,pending=None,uncertain=False,role=None,guild=None,
                sign_state=None,remaining=None,allow=False,sign_attempted=False,
                counts_ready=False,counts={},epoch=0,catalog_token=None,
                catalog_ready=False,price=None,donated=None,
                status='等待組織成員、簽到與捐獻狀態同步')


def decode_actions(packet):
    key=packet.main,packet.sub
    if key not in ((39,15),(39,85),(39,86),(39,87),(10,5)):return None
    r=Reader(packet.payload)
    if key==(39,85):
        state=r.u8()
        if state not in (0,1,2,3):raise ProtocolError('組織簽到狀態無效')
        event=dict(type='guild_sign_state',state=state)
    elif key==(39,86):event=dict(type='guild_sign_result',result=r.u8())
    elif key==(39,87):
        count,allow=r.u8(),r.u8()
        if allow not in (0,1):raise ProtocolError('組織捐獻資格旗標無效')
        event=dict(type='guild_donate_state',remaining=count,allow=bool(allow))
    elif key==(39,15):event=dict(type='guild_action_error',code=r.u8())
    else:
        kind=r.u8()
        if kind==0:event=dict(type='ui_sell_notice')
        elif kind==1:event=dict(type='ui_sell_update',index=r.u8(),count=r.u8())
        elif kind==2:event=dict(type='ui_sell_snapshot',counts={str(i):r.u8() for i in range(1,r.u8()+1)})
        elif kind==3:event=dict(type='ui_sell_day_reset')
        else:raise ProtocolError('未知的介面消費同步種類')
    r.end();return event


def valid_member(state):
    g=state.guild;role=state.player.get('role_id')
    return bool(g.get('ready') and g.get('serial') and str(role) in g.get('members',{}))


def stop_uncertain(d,note):
    d.update(pending=None,uncertain=True,status=note+'；停止重送，請重新登入同步')


def reset_day(d):
    if d['pending']:
        stop_uncertain(d,'組織操作期間收到週期重置')
        return
    d.update(epoch=d['epoch']+1,sign_state=None,remaining=None,allow=False,sign_attempted=False,
             reserved=0,confirmed=0,status='新週期，等待組織簽到與捐獻狀態')


def apply_actions(state,event):
    d=state.guild_actions;kind=event['type'];role=state.player.get('role_id')
    if kind=='role_list_available':state.guild_actions=defaults();return
    if kind=='world_player':
        new_role=event['player']['role_id']
        if d['role'] not in (None,new_role):state.guild_actions=defaults()
        state.guild_actions['role']=new_role
        return
    if kind=='guild_roster':
        serial=state.guild.get('serial')
        if not valid_member(state):
            if d['pending']:stop_uncertain(d,'組織成員身分已失效')
            d.update(guild=None,sign_state=None,remaining=None,allow=False)
        elif d['guild'] not in (None,serial):
            if d['pending']:stop_uncertain(d,'組織身分變動')
            d.update(guild=serial,sign_state=None,remaining=None,allow=False,donate_enabled=False,
                     sign_attempted=False,status='已變更組織，捐獻停用，等待新狀態')
        else:d.update(guild=serial,role=role)
    if kind in ('guild_leave_result','guild_disband_result','guild_member_removed') and not valid_member(state):
        if d['pending']:stop_uncertain(d,'已離開組織')
        d.update(guild=None,sign_state=None,remaining=None,allow=False,donate_enabled=False)
    if kind=='ui_sell_snapshot':d.update(counts=dict(event['counts']),counts_ready=True)
    elif kind=='ui_sell_update':
        if event['index']:d['counts'][str(event['index'])]=event['count']
        p=d['pending']
        if p and p['kind']=='donate' and event['index'] and p['quote']['save_index']==event['index']:
            if event['count']==p['quote']['count']+1:p['sell_ack']=True
            elif event['count']!=p['quote']['count']:stop_uncertain(d,'捐獻消費次數變動不符')
    elif kind=='ui_sell_day_reset':
        reset_day(d);d.update(counts={str(i):0 for i in range(1,101)},counts_ready=True)
    # S39 state has no role/guild ID: never carry observations across an unbound roster.
    if kind.startswith('guild_') and (not valid_member(state) or d['guild']!=state.guild.get('serial')):return
    p=d['pending']
    if kind=='guild_sign_state':
        if d['sign_state']==2 and event['state']==1:
            if d['pending']:stop_uncertain(d,'操作期間簽到狀態重置')
            else:d['sign_attempted']=False
            # Only S10-5 kind 3 resets a monetary budget, never a guessed day.
        d['sign_state']=event['state']
    elif kind=='guild_sign_result':
        if p and p['kind']=='sign':
            if event['result']==0:p['sign_ack']=True
            elif event['result'] in (1,2):
                d.update(pending=None,sign_state=3 if event['result']==1 else 2,
                         status='新加入組織，今日不可簽到' if event['result']==1 else '今日已簽到')
            else:stop_uncertain(d,'組織簽到結果未支援')
    elif kind=='guild_donate_state':
        d.update(remaining=event['remaining'],allow=event['allow'])
        if p and p['kind']=='donate':
            if p['remaining_ack'] and event['remaining']!=p['before_remaining']-1:
                stop_uncertain(d,'已確認的捐獻次數又發生變動')
            elif event['remaining']==p['before_remaining']-1:p['remaining_ack']=True
            elif event['remaining']!=p['before_remaining']:stop_uncertain(d,'捐獻剩餘次數變動不符')
    elif kind=='guild_action_error' and p:
        stop_uncertain(d,'伺服器拒絕組織操作（代碼 '+str(event['code'])+'）')
    elif kind in ('gold_delta','gold_snapshot','gold_limit') and p and p['kind']=='donate':
        if (kind=='gold_delta' and event['delta']==-p['quote']['price'] and not p['gold_ack']
                and state.gold.get('reliable') and state.gold.get('amount')==p['gold_before']-p['quote']['price']):
            p['gold_ack']=True
        else:stop_uncertain(d,'捐獻期間金幣異動無法唯一確認')


def runtime_catalog():
    from wlre.services.world.dynamic_bundle_runtime import current_runtime,current_catalog_token
    token=current_catalog_token();runtime=current_runtime()
    if token!=current_catalog_token():return None,token,'官方資料更新中'
    if not getattr(runtime,'catalog_identity',None):return None,token,'等待當次官方組織消費資料'
    return (getattr(runtime,'guild_catalog',None),token,
            getattr(runtime,'guild_catalog_status','等待同版組織消費資料'))


def common_problem(state):
    from wlre.services.coordination import reason,active
    d=state.guild_actions
    if state.phase!='world_ready' or not state.initial_data_complete or not valid_member(state):
        return '等待角色與自己的組織成員資料同步'
    if d['role']!=state.player.get('role_id') or d['guild']!=state.guild.get('serial'):
        return '組織／角色身分尚未確認'
    if d['uncertain']:return '組織操作結果不明，請重新登入同步'
    if d['pending']:return '等待組織操作與扣款確認'
    pause=reason(state,'guild_actions')
    if pause:return pause
    for service in (state.daily_tasks,state.time_cube,state.maintenance,state.room_storage,state.crafting,state.alchemy,state.expedition):
        if (active(service) or service.get('auto_continue') or service.get('checking')
                or (service is not state.time_cube and service is not state.daily_tasks and service.get('enabled'))):
            return '等待其他背包／消費操作結束'
    for room in state.instances.values():
        if room.get('claim_pending') is not None or room.get('cancel_pending') is not None or room.get('reward_uncertain'):
            return '等待協力領獎確認'
    return ''


def donation_quote(state,catalog):
    from wlre.services.world.guild_catalog import quote
    d=state.guild_actions;level=catalog['levels'].get(state.guild.get('level'))
    if not level:raise ProtocolError('組織等級缺少同版捐獻上限資料')
    if d['remaining'] is None or not d['allow']:raise ProtocolError('等待捐獻資格／剩餘次數，或今日不可捐獻')
    if d['remaining']>level['donate_limit']:raise ProtocolError('捐獻剩餘次數超過同版組織上限')
    done=level['donate_limit']-d['remaining']
    if done>=d['target'] or not d['remaining']:raise ProtocolError('今日捐獻次數已達設定目標')
    try:q=quote(catalog,d['sell_id'],d['counts'],d['counts_ready'])
    except ValueError as exc:raise ProtocolError(str(exc)) from exc
    gold=state.gold
    if not gold.get('ready') or not gold.get('reliable') or type(gold.get('amount')) is not int:
        raise ProtocolError('等待可靠的 S26 金幣同步')
    if q['price']>gold['amount']:raise ProtocolError('金幣不足，暫停組織捐獻')
    if d['reserved']+q['price']>d['budget']:raise ProtocolError('已達本輪金幣消耗上限')
    return q,done


def begin(state,kind,world_acknowledged,now=None):
    if not world_acknowledged:raise ProtocolError('等待世界初始化確認')
    issue=common_problem(state)
    if issue:raise ProtocolError(issue)
    now=time.monotonic() if now is None else now
    d=state.guild_actions;catalog,token,note=runtime_catalog()
    p=dict(kind=kind,role=state.player['role_id'],guild=state.guild['serial'],
           token=token,epoch=d['epoch'],due=now+20)
    if kind=='sign':
        if d['sign_state']!=1:raise ProtocolError('尚未確認可簽到，或今日已簽到／新成員')
        if d['sign_attempted']:raise ProtocolError('本週期已送出簽到要求，不重送')
        d['sign_attempted']=True;p['sign_ack']=False
        packet=Packet(39,69)
    elif kind=='donate':
        if not catalog or d['catalog_token']!=token:raise ProtocolError(note)
        q,done=donation_quote(state,catalog)
        d['reserved']+=q['price']
        p.update(quote=q,before_remaining=d['remaining'],gold_before=state.gold['amount'],gold_ack=q['price']==0,
                 sell_ack=q['save_index']==0,remaining_ack=False)
        packet=Packet(10,5,Writer().u16(q['sell_id']).build())
    else:raise ProtocolError('未知的組織操作')
    d.update(pending=p,status='已送出組織簽到' if kind=='sign' else '已送出金幣捐獻，等待扣款與剩餘次數')
    return [packet]


def command(state,value,world_acknowledged):
    d=state.guild_actions;action=value.get('action')
    if action=='settings':
        if d['pending']:raise ProtocolError('組織操作待確認時不能更改設定')
        for key in ('sign_enabled','donate_enabled'):
            if type(value.get(key)) is not bool:raise ProtocolError('組織自動設定必須為布林值')
        target,budget,sell=value.get('target'),value.get('budget'),value.get('sell_id')
        if type(target) is not int or not 1<=target<=5 or type(budget) is not int or not 0<=budget<=0xffffffff:
            raise ProtocolError('捐獻次數或金幣上限無效')
        if type(sell) is not int or sell not in (8,9,10):raise ProtocolError('捐獻方案無效')
        if value['donate_enabled']:
            catalog,token,note=runtime_catalog()
            if not catalog:raise ProtocolError(note)
            from wlre.services.world.guild_catalog import quote
            try:quote(catalog,sell,d['counts'],d['counts_ready'])
            except ValueError as exc:raise ProtocolError(str(exc)) from exc
        d.update(sign_enabled=value['sign_enabled'],donate_enabled=value['donate_enabled'],
                 target=target,budget=budget,sell_id=sell,settings_revision=d['settings_revision']+1,status='已套用組織自動設定')
        return []
    if action=='pause':
        d.update(sign_enabled=False,donate_enabled=False,settings_revision=d['settings_revision']+1,status='已暫停後續組織操作；已送出的要求仍等待確認')
        return []
    return begin(state,action,world_acknowledged)


def tick(state,world_acknowledged,now=None):
    now=time.monotonic() if now is None else now
    d=state.guild_actions;p=d['pending'];catalog,token,note=runtime_catalog()
    if p:
        if (p['role']!=state.player.get('role_id') or p['guild']!=state.guild.get('serial')
                or not valid_member(state) or p['epoch']!=d['epoch'] or p['token']!=token):
            stop_uncertain(d,'組織操作的角色／組織／版本／週期已失效')
        elif p['kind']=='sign' and p['sign_ack'] and d['sign_state']==2:
            d.update(pending=None,status='伺服器已確認今日組織簽到')
        elif (p['kind']=='donate' and p['gold_ack'] and p['remaining_ack'] and p['sell_ack']
              and d['remaining']==p['before_remaining']-1 and state.gold.get('reliable')):
            d.update(pending=None,confirmed=d['confirmed']+p['quote']['price'],status='伺服器已確認捐獻扣款與剩餘次數')
        elif now>=p['due']:stop_uncertain(d,'組織操作逾時，結果不明')
        return []
    d.update(catalog_ready=bool(catalog),catalog_token=token,price=None,donated=None)
    if catalog:
        try:
            from wlre.services.world.guild_catalog import quote
            d['price']=quote(catalog,d['sell_id'],d['counts'],d['counts_ready'])['price']
            level=catalog['levels'].get(state.guild.get('level'))
            if level and d['remaining'] is not None:d['donated']=level['donate_limit']-d['remaining']
        except ValueError:pass
    if not world_acknowledged or not state.automation['enabled']:return []
    issue=common_problem(state)
    if issue:d['status']=issue;return []
    if d['sign_enabled'] and d['sign_state'] in (None,0):
        d['status']='等待明確的組織簽到狀態';return []
    if d['sign_enabled'] and d['sign_state']==1 and not d['sign_attempted']:
        return begin(state,'sign',True,now)
    if d['donate_enabled']:
        if not catalog:d['status']=note;return []
        try:return begin(state,'donate',True,now)
        except ProtocolError as exc:d['status']=str(exc)
    return []


def disconnect(state):
    d=state.guild_actions
    d.update(sign_enabled=False,donate_enabled=False,
             uncertain=d['uncertain'] or bool(d['pending']),pending=None,status='連線結束，組織自動操作已停止')
