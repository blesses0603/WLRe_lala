"""Sequential Lua alchemy requests, gated on results AND bag consumption."""
from wlre.paths import RESOURCE_ROOT
import json,time,copy
from wlre.network.wire import Packet, Writer, ProtocolError
from wlre.services.items.combat_resources import CAT, item_name, available
META=json.loads(RESOURCE_ROOT.joinpath('alchemy_catalog.json').read_text(encoding='utf8'))['items']
MODES={'無技能':(150,None),'一般':(14,15997),'中階':(87,15998),'高階':(101,15999)}


def defaults():return {'enabled':False,'pending':False,'paused':False,'pause_reason':None,'status':'尚未啟動','completed':0,'requested':0,'history':[]}
def modes(state):
    knowledge=state.get('knowledge',{}).get('player',{});skills=knowledge.get('skills',{})
    return [name for name,(_,sid) in MODES.items() if sid is None or knowledge.get('ready') and skills.get(str(sid),{}).get('level',0)>0]
def material_problem(item):
    sid=str(item.get('item_id'));data=CAT['items'].get(sid);meta=META.get(sid)
    if not data or not meta:return '缺少已核對的材料欄位'
    if item.get('locked'):return '物品已鎖定'
    if any(item.get(k,0) for k in ('beat_level','enhance_level','magic_spar','design_id','saddle_beat_level','star_soul_level','star_soul_kind','modeling')) or any(v.get('value') for v in item.get('plugins',[])):return '附加強化／鑲嵌物品不加入自動消耗'
    if data['restrict']&4 or data['kind'] in (52,54) or not meta['spares'][0] or data['special'] in (142,162,163,197):return '不是可用煉金材料'
    if data['special']==149 and meta['spares'][0]!=73:return '不是可用煉金材料'
    return None

def category(item):
    sid=str(item['item_id']);data=CAT['items'][sid];meta=META[sid]
    if data['special']==141:return 'book'
    if data['special']==149 and meta['spares'][0]==73:return 'partner'
    if data['kind']==20:return 'pet'
    if data['special']==213 and meta['spares'][0] in (4,5):return 'design' if meta['spares'][0]==4 else 'recipe'
    return 'normal'


def aggregate_rows(rows):
    """Keep wire slots separate; count each underlying bag stack once."""
    combined={}
    for row in rows:
        key=str(row['index'])
        if key not in combined:combined[key]=dict(row)
        else:combined[key]['count']+=row['count']
    return list(combined.values())


def prepare(state,command):
    snapshot=state.snapshot();inv=state.inventory
    if not inv.get('ready') or not inv.get('reliable'):raise ProtocolError('包包尚未可靠同步，請重新登入同步')
    mode=command.get('mode','無技能')
    if mode not in modes(snapshot):raise ProtocolError('尚未確認學會此煉金術')
    runs=int(command.get('runs',1))
    if not 1<=runs<=999:raise ProtocolError('執行次數須為1～999')
    rows=copy.deepcopy(command.get('materials',[]));cats=[]
    if not 2<=len(rows)<=5:raise ProtocolError('需要2～5個材料欄位')
    for row in rows:
        index=int(row['index']);count=int(row['count']);item=inv['items'].get(str(index))
        if not 1<=index<=255:raise ProtocolError('材料格位須在1～255')
        if not item or item['item_id']!=int(row['item_id']):raise ProtocolError('材料格位已變更，請重新選取')
        problem=material_problem(item)
        if problem:raise ProtocolError(item_name(item['item_id'])+'：'+problem)
        if not 1<=count<=50:raise ProtocolError('每欄每次用量須為1～50')
        row.update(index=index,count=count,serial=item.get('serial'),initial_count=item['count'])
        cats.append(category(item))
    consumption=aggregate_rows(rows)
    for row in consumption:
        required=row['count']*runs
        if available(inv,row['index'])<required:
            raise ProtocolError(f"包包#{row['index']} {item_name(row['item_id'])}：同格各欄每次合計{row['count']}，{runs}次需要{required}，目前可用{available(inv,row['index'])}（持有{row['initial_count']}）")
    if cats.count('book')>1 or sum(c!='book' for c in cats)<2:raise ProtocolError('至少兩個非百科材料，最多一本百科')
    if 'book' in cats and (cats[-1]!='book' or rows[-1]['count']!=1):raise ProtocolError('百科須放最後一格，每次使用1本')
    kinds={c for c in cats if c!='book'}
    if len(kinds)!=1:raise ProtocolError('一般、夥伴、寵物、設計圖與食譜材料不可混合')
    if kinds!={'normal'} and 'book' in cats:raise ProtocolError('特殊材料不支援搭配百科')
    # Conservative free-space check; the ordinary bag uses rectangular item slots.
    occupied=sum(META.get(str(item['item_id']),{}).get('width',1)*META.get(str(item['item_id']),{}).get('height',1) for item in inv['items'].values())
    if inv.get('capacity',0)-occupied<5:raise ProtocolError('請先保留至少5個空背包格位供產物使用')
    sub=MODES[mode][0] if kinds=={'normal'} else 115
    return {'mode':mode,'runs':runs,'rows':rows,'consumption':consumption,'sub':sub,'role_id':state.player.get('role_id'),'scene':state.player.get('scene')}


class AutoAlchemy:
    def __init__(self):self.plan=None;self.pending=None;self.next_due=0
    def start(self,state,command,now=None):
        now=time.monotonic() if now is None else now
        if state.alchemy.get('enabled') or self.pending:raise ProtocolError('煉金仍在執行或等待回覆')
        plan=prepare(state,command)
        self.plan=plan;self.next_due=now
        state.alchemy={**defaults(),'enabled':True,'requested':plan['runs'],'status':'準備煉金'}
        return self.tick(state,now)
    def pause(self,state,reason):
        if state.alchemy.get('enabled'):state.alchemy.update(paused=True,pause_reason=reason,status=reason+'；保留剩餘次數')
    def stop(self,state,reason='使用者停止'):
        state.alchemy={**state.alchemy,'enabled':False,'paused':False,'pause_reason':None,'status':reason+('；本次已送出，仍等待結果' if self.pending else '')}
    def release(self,state):
        if self.pending:
            for row in self.pending['consumption']:
                key=str(row['index']);remaining=max(0,row['count']-self.pending['deleted'].get(key,0))
                state.inventory['reserved'][key]=max(0,state.inventory['reserved'].get(key,0)-remaining)
        state.inventory['alchemy_slots']=[]
        self.pending=None;state.alchemy['pending']=False
    def observe(self,event,state):
        if not self.pending and not state.alchemy.get('enabled'):return
        k=event['type']
        if k=='battle_start':self.pause(state,'戰鬥中，暫停後續煉金')
        if k=='world_player' or k=='position_snapshot' and event['role_id']==self.plan['role_id'] and event['scene']!=self.plan['scene']:
            self.stop(state,'角色／場景改變，已停止後續煉金')
        if self.pending:
            if k=='alchemy_result':
                if not event.get('item_id') or not event.get('count'):
                    self.stop(state,'伺服器未回覆有效產物，已停止並要求重新同步包包');state.inventory['reliable']=False;self.release(state);return
                if self.pending.get('result') is not None:return
                self.pending['result']={'item_id':event['item_id'],'count':event['count']}
            elif k=='bag_add' and event.get('source')==3:
                sid=str(event['item']['item_id']);self.pending['added'][sid]=self.pending['added'].get(sid,0)+event['item']['count']
            elif k=='bag_delete':
                key=str(event['index']);self.pending['deleted'][key]=self.pending['deleted'].get(key,0)+event['count']
            elif k=='bag_snapshot':
                totals={}
                for value in state.inventory['items'].values():
                    sid=str(value['item_id']);totals[sid]=totals.get(sid,0)+value['count']
                self.pending['snapshot_counts']=totals
                for row in self.pending['consumption']:
                    item=state.inventory['items'].get(str(row['index']))
                    remaining=item['count'] if item and item['item_id']==row['item_id'] else 0
                    consumed=max(0,row['before_count']-remaining)
                    self.pending['deleted'][str(row['index'])]=max(consumed,self.pending['deleted'].get(str(row['index']),0))
            elif k=='alchemy_space_error':
                self.stop(state,'伺服器回覆：背包空間／煉金條件不足');state.inventory['reliable']=False;self.release(state);return
            result=self.pending.get('result')
            produced=False
            if result:
                produced=self.pending['added'].get(str(result['item_id']),0)>=result['count']
                if self.pending.get('snapshot_counts') is not None and result['item_id'] not in {r['item_id'] for r in self.pending['consumption']}:
                    current=self.pending['snapshot_counts'].get(str(result['item_id']),0)
                    produced=produced or current>=self.pending['totals'].get(str(result['item_id']),0)+result['count']
            if result and produced and state.inventory.get('reliable') and all(self.pending['deleted'].get(str(row['index']),0)>=row['count'] for row in self.pending['consumption']):
                state.alchemy['completed']+=1
                record={**result,'round':state.alchemy['completed'],'name':item_name(result['item_id'])}
                state.alchemy['history']=(state.alchemy['history']+[record])[-100:]
                self.release(state);self.next_due=0
                if state.alchemy['completed']>=state.alchemy['requested']:self.stop(state,'設定次數已完成')
                elif state.alchemy['enabled']:state.alchemy['status']='已確認產物入包與材料扣除，準備下一次'
    def tick(self,state,now=None):
        now=time.monotonic() if now is None else now
        plan=self.plan
        if plan and (state.player.get('role_id')!=plan['role_id'] or state.player.get('scene')!=plan['scene']):self.stop(state,'角色／場景改變')
        battle_pause=state.battle.get('active') or state.event_flow.get('blocked') or (state.battle_count and state.battle.get('post_event',{}).get('status')!='completed')
        if self.pending:
            if battle_pause:
                self.pending['battle_paused']=True;self.pause(state,'戰鬥／事件中，等待本次煉金回覆');return []
            if self.pending.pop('battle_paused',False):self.pending['deadline']=now+15
            if now>=self.pending['deadline']:
                self.stop(state,'煉金結果、產物入包或材料扣除未完整確認，已停止；請重新登入同步包包')
                state.inventory['reliable']=False;self.release(state)
            return []
        if not state.alchemy.get('enabled') or now<self.next_due:return []
        if battle_pause:self.pause(state,'戰鬥／戰後事件中，暫停煉金');return []
        supply=state.inventory.get('field_supply',{})
        if supply.get('uncertain'):self.stop(state,'補給結果未確認，請重新登入同步後再煉金');return []
        if supply.get('pending') or any(state.inventory.get('reserved',{}).values()):self.pause(state,'等待補給／包包使用回覆');return []
        state.alchemy.update(paused=False,pause_reason=None)
        try:
            # Revalidate live slots and resources before every packet, with one-run quantities.
            checked=prepare(state,{'mode':plan['mode'],'runs':1,'materials':plan['rows']})
            rows=checked['rows']
            for row,original in zip(rows,plan['rows']):
                if row.get('serial')!=original.get('serial'):raise ProtocolError('材料序號改變，已停止')
            writer=Writer().u8(len(rows))
            for row in rows:writer.u8(row['index']).u8(row['count']);row['before_count']=state.inventory['items'][str(row['index'])]['count']
        except (ValueError,TypeError,KeyError) as exc:self.stop(state,str(exc));return []
        consumption=aggregate_rows(rows)
        for row in consumption:state.inventory['reserved'][str(row['index'])]=row['count']
        state.inventory['alchemy_slots']=[str(row['index']) for row in consumption]
        totals={}
        for value in state.inventory['items'].values():
            sid=str(value['item_id']);totals[sid]=totals.get(sid,0)+value['count']
        self.pending={'rows':rows,'consumption':consumption,'deleted':{},'added':{},'snapshot_counts':None,'totals':totals,'result':None,'deadline':now+15}
        state.alchemy.update(pending=True,status=f'第{state.alchemy["completed"]+1}次已送出，等待煉金結果、產物入包與扣料回覆')
        return [Packet(23,plan['sub'],writer.build())]
