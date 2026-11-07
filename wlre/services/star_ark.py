"""Star Ark server state, bounded dispatch and sequential event execution.

Evidence: StarArk.lua, UIStarArk.lua, Protocols_191.lua and Protocols_075.lua.
No local daily progress fabrication, paid refresh, item shortcut or skill upgrade.
"""
import time
import sqlite3
from wlre.network.wire import Packet,Reader,Writer,ProtocolError
from wlre.storage.ark_questions import QuestionStore,identity as question_identity
from wlre.services.ark_first_answer import solve as solve_first_answer


def defaults():
    return dict(enabled=True,dispatch_enabled=True,fights_enabled=True,questions_enabled=True,pending=None,uncertain=False,
        role=None,ready=False,events_ready=False,planet=0,explore=0,agents={},ship={},events={},main_events={},
        starcoin=dict(ready=False,reliable=False,amount=None,revision=0),
        budget=120,hours=1,reserved=0,confirmed=0,settings_revision=0,catalog_token=None,
        rows=[],quote=None,question=None,answers={},attempted=[],generation=0,
        question_store_status='題庫會保存伺服器確認答對的答案',
        status='等待星之方舟與每日任務同步')


def _bool(r):
    v=r.u8()
    if v not in (0,1):raise ProtocolError('方舟布林旗標無效')
    return bool(v)


def _planet(v,zero=False):
    if not (0 if zero else 1)<=v<=20:raise ProtocolError('方舟星球索引無效')
    return v


def _awards(r):
    count=r.u8()
    if count>32:raise ProtocolError('方舟獎勵數量超出可驗證範圍')
    return [dict(kind=r.u8(),id=r.u32(),value=r.u32()) for _ in range(count)]


def decode_ark(packet):
    r=Reader(packet.payload);sub=packet.sub
    if (packet.main,sub)==(75,24):
        e=dict(type='ark_starcoin',amount=r.u32(),offset=r.u32(),add=_bool(r),show=_bool(r))
    elif packet.main!=191:return None
    elif sub==0:e=dict(type='ark_error',code=r.u8())
    elif sub==1:
        planet=r.u8();explore=r.u16()
        if not 1<=planet<=21 or explore>10000:raise ProtocolError('方舟探索進度無效')
        agents={}
        for _ in range(r.u8()):
            index=r.u8();a=dict(index=index,id=r.u8(),skills=[r.u8(),r.u8()],planet=_planet(r.u8(),True))
            if not index or index in agents or not a['id'] or min(a['skills'])<1:raise ProtocolError('情報員資料無效／重複')
            agents[index]=a
        ship=dict(total=r.u16(),awarded=r.read('h'),remaining=r.u16(),planet=0,agents=[0,0])
        if not 0<=ship['awarded']<=(ship['total']+299)//300 or ship['remaining']>ship['total']:
            raise ProtocolError('搜索艇時間／領獎次數無效')
        assigned=set();ship_planets=[]
        for p in range(1,21):
            ids=[r.u8(),r.u8()];boat=r.u8()
            if boat not in (0,1) or (any(ids) and not boat):raise ProtocolError('星球搜索艇資料不一致')
            if boat:
                ship_planets.append(p);ship.update(planet=p,agents=ids)
            for index in ids:
                if index and (index in assigned or index not in agents or agents[index]['planet']!=p):
                    raise ProtocolError('情報員星球指派不一致')
                if index:assigned.add(index)
        if (len(ship_planets)!=int(bool(ship['total'])) or bool(ship['total'])!=bool(assigned)
                or any(a['planet'] and i not in assigned for i,a in agents.items())):
            raise ProtocolError('搜索艇與情報員配置不一致')
        e=dict(type='ark_snapshot',planet=planet,explore=explore,agents=agents,ship=ship)
    elif sub==2:
        events={}
        for i in range(1,13):
            event=dict(index=i,id=r.u16(),kind=r.u8(),planet=r.u8(),main=False)
            if event['id']:
                _planet(event['planet'])
                if event['id']>=10000 or event['kind'] not in (1,2,3,4):raise ProtocolError('方舟一般事件無效')
            elif event['kind'] or event['planet']:raise ProtocolError('方舟空事件資料不一致')
            events[i]=event
        e=dict(type='ark_events',events=events,new=_bool(r))
    elif sub==3:
        e=dict(type='ark_dispatch',planet=_planet(r.u8()),ship=r.u8(),agents=[r.u8(),r.u8()],total=r.u16())
        if e['ship']!=1 or not any(e['agents']) or not e['total'] or e['agents'][0] and e['agents'][0]==e['agents'][1]:
            raise ProtocolError('方舟派遣回覆無效')
    elif sub==4:
        e=dict(type='ark_collect_reward',total=r.u16())
        e['items']=[dict(id=r.u16(),count=r.u16()) for _ in range(r.u8())]
    elif sub==5:
        e=dict(type='ark_collect_end',planet=_planet(r.u8()),ship=r.u8())
        if e['ship']!=1:raise ProtocolError('方舟搜索艇索引無效')
    elif sub==6:
        e=dict(type='ark_skill',index=r.u8(),skill=r.u8(),level=r.u8())
        if not e['index'] or e['skill'] not in (1,2) or not e['level']:raise ProtocolError('情報員技能更新無效')
    elif sub==7:
        e=dict(type='ark_new_agent',index=r.u8(),id=r.u8())
        if not e['index'] or not e['id']:raise ProtocolError('新增情報員無效')
    elif sub==10:
        e=dict(type='ark_complete',index=r.u8(),id=r.u16())
        if not e['id'] or not 1<=e['index']<=(20 if e['id']>=10000 else 12):raise ProtocolError('方舟完成事件索引無效')
    elif sub==11:
        e=dict(type='ark_question',question=r.u32(),award=dict(kind=r.u8(),id=r.u32(),value=r.u32()),
               options=[r.u32() for _ in range(4)])
        if not e['question'] or not all(e['options']) or len(set(e['options']))!=4:
            raise ProtocolError('方舟問答題目／選項無效')
    elif sub==12:
        e=dict(type='ark_answer_result',correct=_bool(r),answer=r.u8())
        if not 1<=e['answer']<=4:raise ProtocolError('方舟答案索引無效')
    elif sub==15:
        e=dict(type='ark_fight_result',won=_bool(r))
        if e['won']:e.update(id=r.u16(),awards=_awards(r))
    elif sub==16:
        rows={}
        for p in range(1,21):
            row=dict(id=r.u16(),kind=r.u8(),planet=p,index=p,main=True)
            if row['id'] and (row['id']<10000 or row['kind'] not in (1,2,3,4)):
                raise ProtocolError('方舟主線事件無效')
            if not row['id'] and row['kind']:raise ProtocolError('方舟空主線事件無效')
            rows[p]=row
        e=dict(type='ark_main_events',events=rows)
    elif sub==17:
        e=dict(type='ark_explore',planet=r.u8(),explore=r.u16())
        if not 1<=e['planet']<=21 or e['explore']>10000:raise ProtocolError('方舟探索進度無效')
    elif sub==18:
        e=dict(type='ark_main_added',planet=_planet(r.u8()),id=r.u16(),kind=r.u8())
        if e['id']<10000 or e['kind'] not in (1,2,3,4):raise ProtocolError('方舟新增主線無效')
    elif sub==19:
        e=dict(type='ark_collect_count',ship=r.u8(),count=r.read('h'))
        if e['ship']!=1 or e['count']<0:raise ProtocolError('方舟採集領取次數無效')
    else:return None
    r.end();return e


def freeze(d,note):d.update(pending=None,uncertain=True,status=note+'；停止重送，請重新登入同步')


def _question_current(state,p):
    catalog,token,_=runtime_catalog()
    return (catalog is not None and p['token']==token and p['role']==state.player.get('role_id')
            and p['role']==state.star_ark['role']
            and p['daily_generation']==state.daily_tasks['generation'])


def _remember_question(state,p,q,correct=None):
    """A failed private cache must never break the game receive loop."""
    d=state.star_ark
    try:
        key=question_identity(p['token'],p['role'],q)[2]
        store=QuestionStore()
        if correct is None:
            answer,status=store.observe(p['token'],p['role'],q)
            q['known_answer']=answer
            q['answer_source']='永久題庫（伺服器已確認）' if answer is not None else ''
            if status=='unknown':
                answer=solve_first_answer(q)
                if answer is not None:
                    q['known_answer']=answer
                    q['answer_source']='精確算式計算（尚待伺服器確認）'
                    status='computed'
        elif correct:
            answer=q['options'][q['selected']-1]
            status=store.confirm(p['token'],p['role'],q,answer)
            if status=='confirmed':d['answers'][key]=answer
            else:d['answers'].pop(key,None)
        else:
            answer=q['options'][q['selected']-1]
            store.reject(p['token'],p['role'],q,answer,
                candidate=(q.get('answer_source')=='精確算式計算（尚待伺服器確認）'
                           and answer==q.get('known_answer')))
            d['answers'].pop(key,None)
            status='wrong'
        d['question_store_status']={
            'confirmed':'已保存伺服器確認答案；相同角色與版本可跨登入重用',
            'unknown':'已收錄題目；無確認答案且不屬於可精確計算題型，請人工選答',
            'computed':'首次遇題：已精確計算並唯一匹配選項，尚待伺服器確認',
            'conflict':'答案紀錄衝突，已停止此題自動選答',
            'wrong':'此次回答錯誤；不由錯誤回覆推測答案',
        }[status]
    except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
        q['known_answer']=None;q['answer_source']=''
        d['question_store_status']='永久題庫無法讀寫，請人工選答；本次答案未保存'


def apply_ark(state,event):
    d=state.star_ark;kind=event['type']
    if kind=='role_list_available':state.star_ark=defaults();return
    if kind=='world_player':
        role=event['player']['role_id']
        if d['role'] not in (None,role):state.star_ark=defaults()
        state.star_ark['role']=role;return
    if not kind.startswith('ark_') or not d['role'] or d['role']!=state.player.get('role_id'):return
    p=d['pending']
    if (kind in ('ark_question','ark_answer_result') and p and p['kind']=='question'
            and not _question_current(state,p)):
        freeze(d,'問答回覆的角色／版本／每日任務週期已改變');return
    if kind=='ark_starcoin':
        c=d['starcoin'];before=c['amount'];delta=event['offset']*(1 if event['add'] else -1)
        reliable=(not event['offset'] or c['ready'] and c['reliable'] and before+delta==event['amount'])
        c.update(ready=True,reliable=bool(reliable),amount=event['amount'],revision=c['revision']+1)
        if p and p['kind']=='dispatch':
            if (reliable and delta==-p['quote']['price'] and event['offset'] and not p['paid']
                    and event['amount']==p['balance']-p['quote']['price']):p['paid']=True
            else:freeze(d,'派遣期間星力異動無法唯一確認')
    elif kind=='ark_snapshot':
        if p:freeze(d,'方舟操作期間收到完整快照')
        d.update(ready=True,planet=event['planet'],explore=event['explore'],agents=event['agents'],ship=event['ship'])
    elif kind=='ark_events':
        if p and p['kind'] in ('fight','question'):freeze(d,'操作期間方舟事件清單更新')
        d.update(events=event['events'],events_ready=True,generation=d['generation']+1,attempted=[])
    elif kind=='ark_main_events':d['main_events']=event['events']
    elif kind=='ark_explore':d.update(planet=event['planet'],explore=event['explore'])
    elif kind=='ark_main_added':d['main_events'][event['planet']]={**event,'index':event['planet'],'main':True}
    elif kind=='ark_dispatch':
        if not d['ready'] or any(i and i not in d['agents'] for i in event['agents']):
            if p:freeze(d,'派遣回覆含未同步的情報員')
            d['ready']=False;return
        if p and p['kind']=='dispatch':
            q=p['quote']
            if (p['ship_ack'] or event['planet']!=q['planet'] or event['agents']!=[q['agent'],0]
                    or event['total']!=q['duration']):freeze(d,'派遣回覆與要求不符')
            else:p['ship_ack']=True
        d['ship']=dict(total=event['total'],remaining=event['total'],awarded=0,
                       planet=event['planet'],agents=event['agents'])
        for i in event['agents']:
            if i:d['agents'][i]['planet']=event['planet']
    elif kind=='ark_collect_end':
        if d['ship'].get('planet')!=event['planet']:
            if p:freeze(d,'搜索艇結束回覆星球不符')
            d['ready']=False;return
        for i in d['ship']['agents']:
            if i in d['agents']:d['agents'][i]['planet']=0
        d['ship']=dict(total=0,remaining=0,awarded=0,planet=0,agents=[0,0])
    elif kind=='ark_collect_count':
        if d['ship']:d['ship']['awarded']=event['count']
    elif kind=='ark_skill':
        if event['index'] in d['agents']:d['agents'][event['index']]['skills'][event['skill']-1]=event['level']
        if p and p['kind']=='dispatch':freeze(d,'派遣期間情報員技能變更')
    elif kind=='ark_new_agent':
        if event['index'] in d['agents']:
            d['ready']=False
            if p:freeze(d,'新增情報員索引與既有資料衝突')
        else:d['agents'][event['index']]=dict(index=event['index'],id=event['id'],skills=[1,1],planet=0)
    elif kind=='ark_complete':
        group=d['main_events'] if event['id']>=10000 else d['events'];row=group.get(event['index'])
        if row and row['id']==event['id']:row['id']=0
        elif p:freeze(d,'完成事件與伺服器清單不符')
        if p and p['kind'] in ('fight','question'):
            if (event['index'],event['id'])==(p['event']['index'],p['event']['id']):p['complete']=True
            else:freeze(d,'收到其他方舟事件的完成通知')
    elif kind=='ark_fight_result' and p and p['kind']=='fight':
        if not event['won']:
            d.update(pending=None,enabled=False,settings_revision=d['settings_revision']+1,status='方舟戰鬥未獲勝，已停止自動接續')
        elif p['result'] or event['id']!=p['event']['id'] or [a for a in event['awards'] if a['kind']]!=p['awards']:
            freeze(d,'戰鬥事件獎勵與同版資料不符')
        else:p['result']=True
    elif kind=='ark_question':
        if not p or p['kind']!='question' or d['question'] is not None:
            freeze(d,'收到無法對應的方舟問答');return
        if event['award']['kind'] not in (6,22) or event['award']['kind']==6 and event['award']['id']!=8:
            freeze(d,'問答獎勵種類未支援');return
        catalog,token,note=runtime_catalog()
        texts=catalog.get('texts',{}) if catalog and token==p['token'] else {}
        if any(i not in texts for i in [event['question']]+event['options']):
            freeze(d,'問答缺少同版題目文字');return
        d['question']={**event,'selected':None,'text':texts[event['question']],
                       'labels':[texts[i] for i in event['options']]};p['due']=None
        _remember_question(state,p,d['question'])
        d['status']='等待選擇問答答案；沒有已確認答案時不猜題'
    elif kind=='ark_answer_result' and p and p['kind']=='question':
        q=d['question']
        if not q or q['selected'] is None or p['result']:freeze(d,'收到無法對應的問答結果')
        elif event['correct'] and event['answer']!=q['selected']:
            freeze(d,'答對回覆與已送出選項不符')
        else:
            p['result']=True
            _remember_question(state,p,q,event['correct'])
            d['status']='答案正確，等待事件完成' if event['correct'] else '答案錯誤，等待事件完成'
    elif kind=='ark_error' and p:freeze(d,'伺服器拒絕方舟操作（代碼 '+str(event['code'])+'）')


def runtime_catalog():
    from wlre.services.world.dynamic_bundle_runtime import current_runtime,current_catalog_token
    token=current_catalog_token();runtime=current_runtime()
    if token!=current_catalog_token() or not getattr(runtime,'catalog_identity',None):return None,token,'等待當次官方方舟資料'
    return getattr(runtime,'ark_catalog',None),token,getattr(runtime,'ark_catalog_status','等待同版方舟資料')


def problem(state):
    from wlre.services.coordination import reason,active
    d=state.star_ark
    if state.phase!='world_ready' or not state.initial_data_complete or not d['ready'] or d['role']!=state.player.get('role_id'):
        return '等待角色與方舟完整同步'
    if d['uncertain']:return '方舟操作結果不明，請重新登入同步'
    if d['pending']:return '等待方舟操作回覆'
    issue=reason(state,'star_ark')
    if issue:return issue
    for s in (state.daily_tasks,state.time_cube,state.guild_actions,state.room_storage,state.maintenance,
              state.crafting,state.alchemy,state.expedition):
        if active(s) or s.get('checking') or s.get('auto_continue') or s.get('enabled') and s in (state.alchemy,state.expedition):
            return '等待其他背包／消費操作結束'
    if state.local_movement or state.roaming.get('enabled') or state.portal_travel.get('pending'):
        return '請先停止移動／徘徊'
    if any(r.get('claim_pending') is not None or r.get('cancel_pending') is not None or r.get('reward_uncertain')
           for r in state.instances.values()):return '等待協力領獎確認'
    return ''


def task_remaining(state,subtype):
    d=state.daily_tasks
    if (not d['ready'] or not d['groups_ready'] or not d['catalog_ready']
            or d['catalog_token']!=state.star_ark['catalog_token']):return None
    rows=[r for r in d['rows'] if r['cycle']==1 and r['condition_kind']==9 and r['condition_params'][0]==subtype]
    if not rows:return 0
    if any(r['progress'] is None or not r['goal'] for r in rows):return None
    return max(max(0,r['goal']-r['progress']) for r in rows)


def best_dispatch(state,catalog):
    from wlre.services.world.ark_catalog import dispatch_quote
    d=state.star_ark;c=d['starcoin']
    if d['ship'].get('total'):raise ProtocolError('搜索艇正在採集；本功能不自動加速或領回')
    if not c['ready'] or not c['reliable']:raise ProtocolError('等待可靠的 S75-24 星力同步')
    options=[]
    # One idle agent suffices; choose the lowest verified one-hour cost on the
    # first unlocked planet, without changing agent skill levels.
    for a in d['agents'].values():
        if a['planet']:continue
        try:options.append(dispatch_quote(catalog,1,d['hours'],a))
        except ValueError:continue
    if not options:raise ProtocolError('沒有可驗證且空閒的情報員')
    q=min(options,key=lambda q:(q['price'],q['agent']))
    if q['price']>c['amount']:raise ProtocolError('星力不足，暫停派遣')
    if d['reserved']+q['price']>d['budget']:raise ProtocolError('已達本次登入星力消耗上限')
    return q


def _event_key(d,event,token):return (token,d['generation'],event['main'],event['index'],event['id'])


def begin(state,action,world_acknowledged,event=None,now=None):
    if not world_acknowledged:raise ProtocolError('等待世界初始化確認')
    issue=problem(state)
    if issue:raise ProtocolError(issue)
    now=time.monotonic() if now is None else now;d=state.star_ark
    catalog,token,note=runtime_catalog()
    if not catalog or token!=d['catalog_token']:raise ProtocolError(note)
    p=dict(kind=action,role=d['role'],token=token,due=now+20,
           daily_generation=state.daily_tasks['generation'],
           task_before=task_remaining(state,2 if action=='dispatch' else 1))
    if action=='dispatch':
        q=best_dispatch(state,catalog);d['reserved']+=q['price']
        p.update(quote=q,paid=q['price']==0,ship_ack=False,balance=d['starcoin']['amount'])
        packet=Packet(191,1,Writer().u8(q['planet']).u8(q['hours']).u8(q['agent']).u8(0).build())
    elif action in ('fight','question'):
        if not d['events_ready'] or not event or not event['id']:raise ProtocolError('等待方舟事件清單')
        if event['main']:raise ProtocolError('主線事件僅供檢視，不自動推進主線')
        if event['planet']>min(d['planet'],20):raise ProtocolError('事件所在星球尚未開放')
        key=_event_key(d,event,token)
        if key in d['attempted']:raise ProtocolError('此事件已要求執行，等待新事件清單')
        if action=='fight':
            if event['kind']!=1 or event['id'] not in catalog['fights']:raise ProtocolError('沒有同版戰鬥事件資料')
            if not state.auto_battle.get('enabled'):raise ProtocolError('請先啟用並設定自動戰鬥')
            from wlre.services.daily_tasks import slots_needed
            from wlre.services.instance_rewards import bag_claim_problem
            row=catalog['fights'][event['id']];awards=[a for a in row['awards'] if a['kind']]
            # Agent rewards and unknown/lucky-bag rewards require separate
            # capacity evidence and are not authorized by a guessed slot count.
            if row['agent']:raise ProtocolError('事件會新增情報員，尚缺情報員容量驗收')
            needed=slots_needed(awards)
            issue=bag_claim_problem(state.inventory,required_slots=needed)
            if issue:raise ProtocolError(issue)
            expected={}
            for a in awards:
                if a['kind'] in (10,11):expected[a['id']]=expected.get(a['id'],0)+a['value']
            p.update(awards=awards,bag_needed=bool(needed),bag_revision=state.inventory['revision'],
                     bag_expected=expected,bag_before={i:_bag_count(state,i) for i in expected},due=now+180)
            packet=Packet(191,4,Writer().u8(event['index']).u16(event['id']).build())
        else:
            if event['kind']!=3:raise ProtocolError('選取的不是問答事件')
            d['question']=None;p.update(bag_needed=False)
            packet=Packet(191,6,Writer().u8(event['index']).u16(event['id']).build())
        p.update(event=dict(event),complete=False,result=False)
        d['attempted'].append(key)
    else:raise ProtocolError('未知方舟操作')
    d.update(pending=p,status='已送出方舟操作，等待伺服器確認')
    return [packet]


def command(state,value,world_acknowledged,now=None):
    d=state.star_ark;action=value.get('action');now=time.monotonic() if now is None else now
    if action=='pause':
        d.update(enabled=False,settings_revision=d['settings_revision']+1,status='已暫停後續方舟操作；既有要求仍等待確認');return []
    if action=='settings':
        if d['pending']:raise ProtocolError('方舟操作待確認時不能修改設定')
        for k in ('enabled','dispatch_enabled','fights_enabled'):
            if type(value.get(k)) is not bool:raise ProtocolError('方舟自動設定必須為布林值')
        if type(value.get('questions_enabled',d['questions_enabled'])) is not bool:
            raise ProtocolError('問答自動設定必須為布林值')
        if type(value.get('budget')) is not int or not 0<=value['budget']<=0xffffffff:
            raise ProtocolError('星力上限必須為非負整數')
        if type(value.get('hours')) is not int or not 1<=value['hours']<=6:raise ProtocolError('採集時間必須為 1～6 小時')
        d.update({k:value[k] for k in ('enabled','dispatch_enabled','fights_enabled','budget','hours')})
        d['questions_enabled']=value.get('questions_enabled',d['questions_enabled'])
        d.update(settings_revision=d['settings_revision']+1,status='已套用方舟設定');return []
    if action=='answer':
        p=d['pending'];q=d['question'];index=value.get('index')
        if (not world_acknowledged or d['uncertain'] or not p or p['kind']!='question' or not q
                or p['token']!=runtime_catalog()[1] or p['role']!=state.player.get('role_id')
                or p['daily_generation']!=state.daily_tasks['generation']):raise ProtocolError('沒有可回覆的當前方舟問答')
        if type(index) is not int or not 1<=index<=4 or q['selected'] is not None:raise ProtocolError('答案索引無效或已送出')
        q['selected']=index;p['due']=now+20;d['status']='已送出答案，等待結果與事件完成';return [Packet(191,7,bytes([index]))]
    event=None
    if action in ('fight','question'):
        index=value.get('index')
        if type(index) is not int:raise ProtocolError('事件索引必須為整數')
        event=d['events'].get(index)
    return begin(state,action,world_acknowledged,event,now)


def _task_ack(state,p):
    if not p['task_before']:return True
    remaining=task_remaining(state,2 if p['kind']=='dispatch' else 1)
    return remaining is not None and remaining<p['task_before']


def _bag_count(state,item_id):
    return sum(r['count'] for r in state.inventory['items'].values() if r['item_id']==item_id)


def _bag_ack(state,p):
    return (not p['bag_needed'] or state.inventory.get('reliable')
        and state.inventory['revision']>p['bag_revision']
        and all(_bag_count(state,i)>=p['bag_before'][i]+n for i,n in p['bag_expected'].items()))


def tick(state,world_acknowledged,now=None):
    now=time.monotonic() if now is None else now;d=state.star_ark;p=d['pending']
    catalog,token,note=runtime_catalog()
    if p:
        if (p['role']!=state.player.get('role_id') or p['token']!=token
                or p['daily_generation']!=state.daily_tasks['generation']):freeze(d,'角色／版本／每日任務週期已改變')
        elif (p['kind']=='fight' and state.battle.get('active')
              and state.battle.get('war_style') not in (None,19)):
            freeze(d,'收到無法對應的戰鬥類型')
        elif p['kind']=='dispatch' and p['paid'] and p['ship_ack'] and _task_ack(state,p):
            d.update(pending=None,confirmed=d['confirmed']+p['quote']['price'],status='伺服器已確認派遣與星力扣除')
        elif (p['kind'] in ('fight','question') and p['complete'] and p['result'] and _task_ack(state,p)
              and not state.battle.get('active') and _bag_ack(state,p)):
            d.update(pending=None,question=None,status='伺服器已確認方舟事件完成；每日進度另以 S124 為準')
        elif p['due'] is not None and now>=p['due']:freeze(d,'方舟操作逾時，結果不明')
        elif (p['kind']=='question' and d['question'] and d['question']['selected'] is None
              and d['enabled'] and d['questions_enabled'] and state.automation['enabled']):
            q=d['question']
            if q.get('known_answer') is not None:
                _remember_question(state,p,q)
                answer=q.get('known_answer')
                if answer in q['options']:
                    packets=command(state,dict(action='answer',index=q['options'].index(answer)+1),world_acknowledged,now)
                    d['status']='已依'+q.get('answer_source','確認答案')+'送出答案，等待伺服器結果與事件完成'
                    return packets
        return []
    if d['catalog_token']!=token:
        if d['catalog_token'] is not None:
            d.update(enabled=False,answers={},attempted=[],status='官方資料已變更，方舟自動接續已暫停')
        d['catalog_token']=token
    d['quote']=None;d['rows']=[]
    if catalog:
        try:d['quote']=best_dispatch(state,catalog)
        except ProtocolError:pass
        for row in list(d['events'].values())+list(d['main_events'].values()):
            if not row['id']:continue
            definition=catalog['fights'].get(row['id'],{}) if row['kind']==1 else {}
            d['rows'].append({**row,'name':definition.get('name',f'事件 {row["id"]}'),
                'execution':('主線僅供檢視' if row['main'] else
                    {1:'沿用已啟用的自動戰鬥',2:'交付物品尚未自動代做',3:'已知答案可自動回覆；未知答案需選擇',4:'商人購買尚未自動代做'}[row['kind']])})
    if not world_acknowledged or not d['enabled'] or not state.automation['enabled']:return []
    issue=problem(state)
    if issue:d['status']=issue;return []
    if not catalog:d['status']=note;return []
    dispatch_needed=task_remaining(state,2);events_needed=task_remaining(state,1)
    if dispatch_needed is None or events_needed is None:
        d['status']='等待當期每日方舟任務與進度';return []
    if dispatch_needed and d['dispatch_enabled']:
        try:return begin(state,'dispatch',True,now=now)
        except ProtocolError as exc:d['status']=str(exc)
    if events_needed and (d['fights_enabled'] or d['questions_enabled']):
        failures=[]
        for event in sorted(d['events'].values(),key=lambda e:e['index']):
            if not event['id']:continue
            action=None
            if event['kind']==1 and d['fights_enabled']:action='fight'
            elif event['kind']==3 and d['questions_enabled']:action='question'
            if action is None:continue
            try:return begin(state,action,True,event,now)
            except ProtocolError as exc:failures.append(str(exc))
        d['status']='尚有方舟探索次數；'+('；'.join(dict.fromkeys(failures)) if failures else '目前沒有可自動執行的戰鬥／問答事件，請查看事件限制')
    elif not dispatch_needed and not events_needed:d['status']='當日方舟任務已達標或未列入當期任務'
    return []


def disconnect(state):
    d=state.star_ark;d.update(enabled=False,uncertain=d['uncertain'] or bool(d['pending']),pending=None,
                            ready=False,status='連線結束，方舟自動操作已停止')
