"""Supported AutoPlay.lua rule ordering, using current validated command adapters."""
import copy
import math
from wlre.services.items import recovery, maintenance;from wlre.services.battle import party_guard
from wlre.services.battle.battle_commands import owned_units, slot, action_command
from wlre.network.wire import ProtocolError
from wlre.services.items.combat_resources import CAT, best_skill_command, learned_command, food_command, field_context

ACTION_IDS={-1:'auto_skill',-2:'heal_hp',-3:'heal_sp',10001:'normal',60021:'defend',60041:'escape',10008:'catch'}
REASONS={'deadAction':'同方陣亡','enemyHpAction':'敵方HP條件','lowHpAction':'自方HP條件',
         'lowSpAction':'自方SP條件','roundAction':'指定回合','repeatAction':'循環行動',
         'orderAction':'順序行動','fallback':'最後普攻'}

def action(sid=0,**kw):return {'id':sid,'kind':1,'target':1,**kw}

def default_profile():
    return {'bDeadAction':False,'deadAction':action(60021),
        'bEnemyHPAction':False,'enemyHpAction':action(10008,compareKind=2,value=100),
        'bLowHpAction':True,'lowHpAction':action(-2,kind=2,notice=2,value=100),
        'bLowSpAction':False,'lowSpAction':action(60021,notice=2,value=20),
        'bRoundAction':False,'roundAction':[action() for _ in range(3)],
        'bRepeatAction':False,'repeatAction':[action() for _ in range(5)],
        'bOrderAction':True,'orderAction':[action(10001),action()]}

def defaults():
    profiles={'player':default_profile(),'partner':default_profile()}
    profiles['partner']['lowHpAction']['notice']=3
    profiles['partner']['lowSpAction']['notice']=3
    return {'bPlayerDieCloseAI':False,'bNPCDieCloseAI':False,'field_heal':False,'field_hp_percent':60,'field_sp_percent':30,'profiles':profiles,'recovery':recovery.defaults(),'party_guard':party_guard.defaults(),'maintenance':maintenance.defaults()}

def validate(settings):
    if not isinstance(settings,dict):raise ProtocolError('AI設定須為JSON物件')
    result=defaults()
    if set(settings)-set(result):raise ProtocolError('AI設定含未支援欄位')
    for key in ('bPlayerDieCloseAI','bNPCDieCloseAI','field_heal'):
        if key in settings:
            if type(settings[key]) is not bool:raise ProtocolError(key+'須為布林值')
            result[key]=settings[key]
    for key in ('field_hp_percent','field_sp_percent'):
        if key in settings:
            if type(settings[key]) is not int or not 0<=settings[key]<=100:raise ProtocolError('戰後補給門檻須為0～100百分比')
            result[key]=settings[key]
    if 'party_guard' in settings:result['party_guard']=party_guard.validate(settings['party_guard'])
    if 'maintenance' in settings:result['maintenance']=maintenance.validate(settings['maintenance'])
    if 'recovery' in settings:result['recovery']=recovery.validate(settings['recovery'])
    else:
        for res in ('hp','sp'):
            for who in ('player','partner'):result['recovery'][res][who+'_percent']=result['field_'+res+'_percent']
    profiles=settings.get('profiles',{})
    if not isinstance(profiles,dict) or set(profiles)-{'player','partner'}:raise ProtocolError('未知AI角色設定')
    for who,data in profiles.items():
        if not isinstance(data,dict) or set(data)-set(result['profiles'][who]):raise ProtocolError('未知AI規則欄位')
        profile=result['profiles'][who]
        for key,value in data.items():
            if key.startswith('b'):
                if type(value) is not bool:raise ProtocolError(key+'須為布林值')
                profile[key]=value;continue
            many=key in ('roundAction','repeatAction','orderAction')
            count={'roundAction':3,'repeatAction':5,'orderAction':2}.get(key,1)
            values=value if many else [value]
            if not isinstance(values,list) or len(values)>count:raise ProtocolError(key+'行動數量錯誤')
            checked=[]
            for row in values:
                base=profile[key][0] if many else profile[key]
                if not isinstance(row,dict) or set(row)-set(base)-{'bUseNextSkill'}:raise ProtocolError('未知AI行動欄位')
                entry={**base,**row}
                if type(entry['id']) is not int:raise ProtocolError('AI行動ID須為整數')
                if entry['id'] in (-2,-3):entry['kind']=2
                if type(entry['kind']) is not int or entry['kind'] not in (1,2):raise ProtocolError('kind須為1特技或2包包道具')
                if entry['kind']==1:
                    if entry['id'] not in {0,*ACTION_IDS} and str(entry['id']) not in CAT['skills']:raise ProtocolError('特技不在目前版本資料表')
                elif entry['id'] not in (0,-2,-3) and CAT['items'].get(str(entry['id']),{}).get('kind') not in (23,32):raise ProtocolError('補給僅支援包包食物／料理')
                if entry['kind']==2 and entry.get('bUseNextSkill'):raise ProtocolError('道具沒有次階特技')
                if entry['target'] not in (1,2,3):raise ProtocolError('未知目標選擇種類')
                if 'notice' in entry and entry['notice'] not in (1,2,3):raise ProtocolError('notice須為1同方、2角色、3夥伴')
                if 'compareKind' in entry and entry['compareKind'] not in (1,2):raise ProtocolError('compareKind須為1大於、2小於')
                if 'value' in entry and (type(entry['value']) not in (int,float) or not math.isfinite(entry['value']) or entry['value']<0):raise ProtocolError('HP/SP門檻須為非負數值')
                checked.append(entry)
            profile[key]=checked+[action() for _ in range(count-len(checked))] if many else checked[0]
    return copy.deepcopy(result)

def ordered_units(state):return sorted(state.get('battle_units',{}).values(),key=lambda u:(u['col'],u['row']))

def choose_action(state,actor,profile):
    pid=state['player']['role_id'];same=lambda u:(u['col']>2)==(actor['col']>2)
    living=[u for u in ordered_units(state) if u.get('hp',0)>0 and not u.get('exited')]
    def resolve(data,target=None):
        if not data or not data['id']:return None
        if data.get('kind')==2:
            resource='sp' if data['id']==-3 else data.get('resource','hp')
            try:return food_command(state,actor,resource,None if data['id']<0 else data['id'],target)
            except ProtocolError:return None
        if data['id']==-1:
            try:return best_skill_command(state,actor,target,data['target'])
            except ProtocolError:return None
        if data['id'] not in ACTION_IDS:
            try:return learned_command(state,actor,data['id'],target,data['target'],data.get('bUseNextSkill',False))
            except ProtocolError:return None
        mode=ACTION_IDS[data['id']]
        if target is not None or mode in ('defend','escape'):
            try:return action_command(state,actor,mode,target)
            except ProtocolError:return None
        enemies=[u for u in living if not same(u)]
        candidates=sorted(enemies,key=lambda u:((-u['hp'] if data['target']==3 else u['hp']),u['col'],u['row']))
        for u in candidates:
            try:return action_command(state,actor,mode,slot(u))
            except ProtocolError:continue
        return None
    def done(key,data,target=None):
        cmd=resolve(data,target)
        return (cmd,REASONS[key]) if cmd else None
    if profile['bDeadAction'] and any(same(u) and u.get('hp',1)<=0 and not u.get('exited') and not u.get('is_fly') for u in ordered_units(state)):
        data=profile['deadAction']
        target=next((f"{u['col']}:{u['row']}" for u in ordered_units(state) if same(u) and u.get('hp',1)<=0 and not u.get('exited')),None)
        revive=CAT['skills'].get(str(data['id']),{}).get('FightWay') in (8,24)
        if result:=done('deadAction',data,target if revive else None):return result
    data=profile['enemyHpAction']
    if profile['bEnemyHPAction']:
        for u in living:
            if same(u) or not ((data['compareKind']==1 and u['hp']>data['value']) or (data['compareKind']==2 and u['hp']<data['value'])):continue
            if result:=done('enemyHpAction',data,slot(u)):return result
    for flag,key,attr in (('bLowHpAction','lowHpAction','hp'),('bLowSpAction','lowSpAction','sp')):
        data=profile[key]
        if profile[flag]:
            notice=data['notice']
            match=any(u.get(attr,float('inf'))<data['value'] and (
                (notice==1 and same(u)) or (notice==2 and u['pid']==pid) or (notice==3 and u.get('master_id')==pid)) for u in living)
            if match:
                target=None
                if data.get('kind')==2 or CAT['skills'].get(str(data['id']),{}).get('TargetKind') in (1,3,5):
                    target=next((f"{u['col']}:{u['row']}" for u in living if u.get(attr,float('inf'))<data['value'] and ((notice==1 and same(u)) or (notice==2 and u['pid']==pid) or (notice==3 and u.get('master_id')==pid))),None)
                resource_data=dict(data)
                if key=='lowSpAction' and resource_data.get('kind')==2:resource_data['resource']='sp'
                if result:=done(key,resource_data,target):return result
    round_number=state['battle'].get('round',0)
    if profile['bRoundAction'] and 1<=round_number<=3:
        if result:=done('roundAction',profile['roundAction'][round_number-1]):return result
    if profile['bRepeatAction']:
        used=[a for a in profile['repeatAction'] if a['id']]
        if used:
            if result:=done('repeatAction',used[(round_number-1)%len(used)]):return result
    target_kind=1
    if profile['bOrderAction']:
        for data in profile['orderAction']:
            if data['id']:target_kind=data['target']
            if result:=done('orderAction',data):return result
    # Original fallback scans slots when there is no prior target preference.
    if not profile['bOrderAction'] or not any(a['id'] for a in profile['orderAction']):
        for unit in living:
            if not same(unit):
                if result:=done('fallback',action(10001),slot(unit)):return result
    elif result:=done('fallback',action(10001,target=target_kind)):return result
    raise ProtocolError('沒有可用行動／目標，或普攻資料不足')

class AutoBattle:
    delay=0
    def __init__(self):
        self.enabled=False;self.settings=defaults();self.key=None;self.failed_key=None
        self.decided=set();self.due=0;self.roster=set();self.field_wait_key=None
    def status(self,state,status,reason='',**fields):
        value={**state.auto_battle,'enabled':self.enabled,'status':status,'reason':reason,**fields}
        if value!=state.auto_battle:state.auto_battle=value
    def start(self,state,settings):
        self.settings=validate(settings);self.field_wait_key=None;self.enabled=True;self.key=None;self.failed_key=None;self.decided=set()
        self.status(state,'armed','等待新回合／本回合可操作單位')
    def stop(self,state,reason='使用者停止AI'):
        self.enabled=False;self.status(state,'disabled',reason)
    def tick(self,state,logic,now):
        if not self.enabled or not logic.world_acknowledged:return []
        if state.maintenance.get('pending') or state.maintenance.get('uncertain'):
            self.status(state,'maintenance',state.maintenance.get('status','等待戰後修理／整理'));return []
        battle=state.battle
        snap=state.snapshot();all_owned=owned_units(snap,False);pid=state.player.get('role_id')
        death_check=battle.get('active') or (state.battle_count>0 and battle.get('post_event',{}).get('status')!='completed')
        if death_check and any(u.get('hp',1)<=0 and self.settings['bPlayerDieCloseAI' if u['pid']==pid else 'bNPCDieCloseAI'] for u in all_owned):
            self.stop(state,'設定的角色／夥伴陣亡停機條件成立');logic.roaming.stop(state,logic.movement,'AI陣亡停機');return []
        if not battle.get('active') or battle.get('round',0)<=0:
            if self.settings['field_heal'] and not battle.get('active'):
                packets=self.heal_field(state,logic,now)
                if packets is not None:return packets
            self.status(state,'armed','等待戰鬥回合');return []
        if battle.get('war_style') in (16,21,23,24):
            self.status(state,'paused','此特殊戰鬥尚未開放自動下令');return []
        key=(state.battle_count,battle['round'])
        if key!=self.key:
            self.key=key;self.decided=set();self.due=now+self.delay
            self.roster={(slot(u),u['pid']) for u in owned_units(snap)}
        if self.failed_key==key:return []
        if now<self.due:
            self.status(state,'waiting','等待回合資料安定');return []
        pending=[u for u in owned_units(snap) if (slot(u),u['pid']) in self.roster
                 and slot(u) not in self.decided and slot(u) not in battle.get('commands',{})
                 and not (logic.round_key==key and (u['col'],u['row']) in logic.sent_units)]
        if not pending:
            self.status(state,'waiting','本回合已下令，等待下一回合');return []
        guard_reason=party_guard.escape_reason(snap,self.settings['party_guard'])
        old_key,old_units=logic.round_key,set(logic.sent_units)
        old_reserved=copy.deepcopy(state.inventory['reserved'])
        try:
            decisions=[]
            for u in pending:
                profile=self.settings['profiles']['player' if u['pid']==pid else 'partner']
                try:
                    if guard_reason:cmd,reason=action_command(snap,u,'escape'),guard_reason
                    else:cmd,reason=choose_action(snap,u,profile)
                except ProtocolError as exc:raise ProtocolError(f"{u.get('name',slot(u))}：{exc}") from exc
                for cost in cmd.get('resource_reservations',[]):
                    index=str(cost['index']);snap['inventory']['reserved'][index]=snap['inventory']['reserved'].get(index,0)+cost['count']
                decisions.append({'unit':u.get('name',slot(u)),'slot':slot(u),'reason':reason,'command':cmd})
            packets=[]
            for d in decisions:packets.extend(logic.command(d['command'],state))
        except (ValueError,KeyError,TypeError) as exc:
            logic.round_key,logic.sent_units=old_key,old_units;state.inventory['reserved']=old_reserved;self.failed_key=key
            self.status(state,'blocked',str(exc));logic.roaming.stop(state,logic.movement,'AI指令資料不足，停止徘徊');return []
        self.decided.update(slot(u) for u in pending)
        self.status(state,'submitted','已準備本回合指令，送出後等待伺服器結果',decisions=decisions)
        return packets

    def heal_field(self,state,logic,now):
        if state.event_flow.get('blocked') or (state.battle_count and state.battle.get('post_event',{}).get('status')!='completed'):return None
        context,actor=field_context(state.snapshot())
        guard=logic.field_supply
        if guard.uncertain:
            self.stop(state,'前次補給結果未確認，請重新登入同步');logic.roaming.stop(state,logic.movement,'補給待確認');return []
        if guard.pending:
            logic.movement.stop(state,'等待補給回覆');self.status(state,'waiting_heal','等待同一物品扣除及同一對象 HP／SP 回覆');return []
        if state.alchemy.get('pending'):
            if recovery.needed(context,self.settings):
                logic.movement.stop(state,'等待本次煉金包包回覆，再補給')
                self.status(state,'waiting_heal','等待本次煉金包包回覆，再檢查補給');return []
            return None
        wait_key=(state.inventory.get('revision'),state.inventory.get('ready'),state.inventory.get('reliable'),state.inventory.get('use_failed'),
            repr(state.inventory.get('reserved')),repr(state.potion_storage),
            tuple((key,u.get('pid'),u.get('hp'),u.get('sp'),u.get('max_hp'),u.get('max_sp')) for key,u in context['battle_units'].items()))
        if wait_key==self.field_wait_key:return []
        self.field_wait_key=None
        missing_supply=None
        for key,unit in context['battle_units'].items():
            if unit.get('hp',0)<=0:continue
            for resource in ('hp','sp'):
                config=self.settings['recovery'][resource]
                who='partner' if unit.get('npc_index',0) else 'player'
                maximum=unit.get('max_'+resource,0);value=unit.get(resource,0)
                if not maximum or value>=maximum*config[who+'_percent']/100:continue
                try:cmd=recovery.choose(context,actor,unit,key,resource,config)
                except ProtocolError as exc:missing_supply=str(exc);continue
                if cmd is None:continue
                cmd['npc_index']=unit.get('npc_index',0)
                packets=logic.command(cmd,state)
                logic.movement.stop(state,'自動補給，等待回覆')
                self.status(state,'healing',('使用藥水儲存槽，等待伺服器回覆' if cmd['type']=='field_storage' else '依設定從包包取用補給，等待伺服器回覆'),decisions=[{'unit':unit.get('name',''),'slot':key,'reason':'戰後包包補'+resource.upper(),'command':cmd}])
                return packets
        if missing_supply:
            self.field_wait_key=wait_key;logic.roaming.stop(state,logic.movement,'戰後補給不足，停止徘徊')
            self.status(state,'waiting_heal',missing_supply);return []
        return None

def summary(value):
    labels={'disabled':'已停止','armed':'AI待命','paused':'AI暫停','waiting':'AI等待','submitted':'AI本回合下令','blocked':'AI本回合未送出','healing':'AI包包補給','waiting_heal':'AI補給待確認'}
    return labels.get(value.get('status'),'尚未啟動')+'｜'+value.get('reason','')
