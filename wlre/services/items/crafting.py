"""1262 Room.lua server smith schedule; manual submissions, confirmed execution."""
from wlre.core.state_ownership import writes
from wlre.services.items import reservations
from wlre.services.coordination import reason as coordination_reason
from wlre.paths import RESOURCE_ROOT
import json,time
from wlre.network.wire import Packet, Reader, Writer, ProtocolError
from wlre.services.items.combat_resources import item_name, available

RECIPES=json.loads(RESOURCE_ROOT.joinpath('crafting_catalog.json').read_text(encoding='utf-8'))['recipes']
SPEED={39053:15,39007:2,39045:3,37202:3}

def confirmed_unlocked(recipe):
    """Only unconditional recipes are confirmed until library marks sync exists."""
    return bool(recipe) and recipe.get('open_used',0)==0 and not any(recipe.get(k,0) for k in ('design_id','time_id','limit_kind'))

def defaults():return {'ready':False,'queue':{},'active':0,'started_at':None,'running':False,'auto_continue':False,'pending':None,'completion_requested':False,'completed':0,'status':'等待製作排程同步','revision':0,'human_index':0,'human_id':0,'uncertain':False}
def room_defaults():return {'owner':None,'current_owner':None,'ready':False,'items':{},'revision':0}

def schedule_record(r):
    row={'index':r.u8(),'item_id':r.u16(),'elapsed':r.u32()/1000,'count':r.u8(),'base_time':r.u32()}
    if not 1<=row['index']<=255 or not row['item_id'] or not row['count']:raise ProtocolError('製作排程欄位無效')
    return row

def furniture_record(r,index):
    d={'index':index,'item_id':r.u16(),'x':r.u16(),'y':r.u16(),'z':r.u16(),'direction':r.u8(),'workbench':r.u16()}
    d['contents']=[r.u16() for _ in range(11)];d.update(floor=r.u8(),status=r.u8());r.take(7);return d

def decode_crafting(packet):
    main,sub=packet.main,packet.sub;r=Reader(packet.payload);e={'main':main,'sub':sub}
    if main==64:
        if sub==1:
            if len(packet.payload)<1 or (len(packet.payload)-1)%12:raise ProtocolError('製作排程長度不符')
            rows=[schedule_record(r) for _ in range((r.remaining-1)//12)]
            if len({v['index'] for v in rows})!=len(rows):raise ProtocolError('製作排程索引重複')
            e.update(type='craft_snapshot',rows=rows,active=r.u8())
        elif sub==16:e.update(type='craft_added',row=schedule_record(r))
        elif sub in (2,3,5):e.update(type={2:'craft_started',3:'craft_paused',5:'craft_deleted'}[sub],index=r.u8())
        elif sub in (4,6,7,8):e.update(type='craft_completed' if sub==4 else 'craft_failed',index=r.u8(),points=r.u16(),reason={4:'製作完成',6:'包包空間不足',7:'住宅空間不足',8:'器具數量已達上限'}[sub])
        elif sub==10:e.update(type='craft_human',index=r.u8(),npc_id=r.u32())
        elif sub==25:
            e.update(type='craft_swapped',success=r.u8()==1)
            if e['success']:e.update(first=r.u8(),second=r.u8())
        else:return None
    elif main==62 and sub in (1,2,4,5,76):
        e.update(type='navigation_geometry_change',geometry_scope='house',affects_geometry=True,geometry_rebuilt=False,details_parsed=True)
        if sub==4:
            owner=r.u32()
            if r.remaining%44:raise ProtocolError('小屋家具資料長度不符')
            rows=[furniture_record(r,r.u16()) for _ in range(r.remaining//44)]
            e.update(reason='furniture_snapshot',room_action='snapshot',owner=owner,furniture=rows,affects_geometry=bool(rows))
        elif sub==1:
            kind=r.u8();index=r.u16();d=furniture_record(r,index)
            e.update(reason='furniture_added',room_action='add',kind=kind,furniture=d)
        elif sub==2:e.update(reason='furniture_removed',room_action='remove',index=r.u16())
        elif sub==76:e.update(reason='furniture_retained',room_action='retain',index=r.u16())
        else:
            kind=r.u8();index=r.u16();item=r.u16();bench=r.u16()
            e.update(reason='furniture_added',room_action='tool',kind=kind,index=index,item_id=item,workbench=bench)
    else:return None
    r.end();return e

def compact(c):
    c['queue']={str(i):{**row,'index':i} for i,row in enumerate(sorted(c['queue'].values(),key=lambda x:x['index']),1)}

def elapsed(c,row,now):return row['elapsed']+(max(0,now-c['started_at']) if c['running'] and row['index']==c['active'] and c['started_at'] is not None else 0)


def effective_time(state,row):
    data=state if isinstance(state,dict) else state.__dict__
    room=data.get('furniture',{});c=data.get('crafting',{})
    if not room.get('ready'):return None
    available_tools={v['item_id'] for v in room['items'].values() if v.get('status')==0}
    percent=1-sum(value/100 for sid,value in SPEED.items() if sid in available_tools)
    if c.get('human_index'):
        npc=data.get('knowledge',{}).get('companions',{}).get(str(c['human_index']))
        if not npc or npc.get('npc_id')!=c['human_id']:return None
        faith=npc['stats'].get('faith',0)
        percent-=(.04 if faith>75 else .03 if faith>50 else .02 if faith>25 else .01 if faith>0 else 0)
    return max(1,row['base_time']*percent)

def apply_crafting(state,event):
    c=state.crafting;room=state.furniture;k=event['type'];now=time.monotonic()
    if k=='initial_data_complete' and room.get('personal_batch') and room.get('owner')==state.player.get('role_id'):
        room['ready']=True;room['revision']+=1
    action=event.get('room_action')
    if action:
        if action=='snapshot':
            room['current_owner']=event['owner']
            if event['owner']==state.player.get('role_id'):
                room.update(owner=event['owner'],ready=True,items={str(r['index']):r for r in event['furniture']})
        elif event.get('kind')==2 or room['current_owner']==state.player.get('role_id'):
            if event.get('kind')==2 and action=='add':room.update(owner=state.player.get('role_id'),personal_batch=True)
            if action=='add':room['items'][str(event['furniture']['index'])]=event['furniture']
            elif action=='remove':room['items'].pop(str(event['index']),None)
            elif action=='retain' and str(event['index']) in room['items']:room['items'][str(event['index'])]['status']=1
            elif action=='tool':
                if event['kind']==1:room['items'][str(event['index'])]={'index':event['index'],'item_id':event['item_id'],'workbench':event['workbench'],'status':0,'floor':0}
                else:room['items'].pop(str(event['index']),None)
        room['revision']+=1
    if not k.startswith('craft_'):return
    c['revision']+=1
    if k=='craft_snapshot':
        c.update(ready=True,queue={str(r['index']):r for r in event['rows']},active=event['active'],running=bool(event['active']),started_at=now,completion_requested=False)
        if event['active'] and str(event['active']) not in c['queue']:c.update(running=False,uncertain=True,status='製作索引缺資料，請重新同步')
        else:c.update(uncertain=False,status='伺服器製作排程已同步')
    elif k=='craft_added':c['queue'][str(event['row']['index'])]=event['row'];c['status']='已加入伺服器製作排程'
    elif k=='craft_started':
        if str(event['index']) not in c['queue']:c.update(uncertain=True,status='製作索引缺資料，停止自動接續');return
        c.update(active=event['index'],running=True,started_at=now,completion_requested=False,status='製作中（伺服器確認）')
    elif k=='craft_paused':
        row=c['queue'].get(str(event['index']))
        if row:row['elapsed']=elapsed(c,row,now)
        c.update(active=0,running=False,started_at=None,auto_continue=False,status='已暫停製作（伺服器確認）')
    elif k=='craft_completed':
        # Ignore duplicate completion replies once the row has been removed.
        if c['running'] and event['index']==c['active'] and c['queue'].pop(str(event['index']),None) is not None:
            c['completed']+=1;compact(c)
            c.update(active=0,running=False,started_at=None,completion_requested=False,status='製作完成，等待確認產物／包包更新')
    elif k=='craft_failed':c.update(running=False,active=0,auto_continue=False,completion_requested=False,status=event['reason'])
    elif k=='craft_deleted':
        c['queue'].pop(str(event['index']),None);compact(c);c['status']='已移除製作排程（伺服器確認）'
    elif k=='craft_human':c.update(human_index=event['index'],human_id=event['npc_id'])
    elif k=='craft_swapped':
        a,b=str(event.get('first')),str(event.get('second'))
        if event['success'] and a in c['queue'] and b in c['queue']:
            c['queue'][a],c['queue'][b]=c['queue'][b],c['queue'][a]
            c['queue'][a]['index']=int(a);c['queue'][b]['index']=int(b)
        c['status']='製作順序已更新' if event['success'] else '伺服器拒絕交換製作順序'

def tools(state):return {int(v['item_id']):int(v['index']) for v in state.furniture['items'].values() if v.get('status')==0}

def tool_for(state,item_id):
    if not state.furniture['ready'] or state.furniture['owner']!=state.player.get('role_id'):raise ProtocolError('請先進入自己的帳篷，取得工作設備資料')
    index=tools(state).get(item_id)
    if index is None:raise ProtocolError('缺少已確認擺放的工作設備：'+item_name(item_id))
    return index

def recipe_plan(state,item_id,count):
    r=RECIPES.get(str(item_id))
    if not r:raise ProtocolError('找不到這個製作配方')
    if r.get('open_used',0)!=0:raise ProtocolError('此製作物在目前版本尚未開放')
    if not isinstance(count,int) or isinstance(count,bool) or not 1<=count<=255:raise ProtocolError('製作批數必須為 1～255')
    if r['design_id']:raise ProtocolError('此配方需要圖紙解鎖；圖鑑狀態尚未同步，未送出')
    if r['time_id'] or r['limit_kind']:raise ProtocolError('此配方有活動時間或次數限制，目前無法確認條件，未送出')
    tool=tool_for(state,r['tool_id']);c=state.crafting
    if not c['ready']:raise ProtocolError('製作排程尚未同步')
    if len(c['queue'])>=(5 if 39050 in tools(state) else 3):raise ProtocolError('製作排程已滿')
    if any(row['item_id']==item_id for row in c['queue'].values()) and 39814 not in tools(state):raise ProtocolError('排程已有相同物品，需原版允許重複製作的家具')
    inv=state.inventory
    if not inv.get('ready') or not inv.get('reliable'):raise ProtocolError('背包資料尚未同步或不可靠')
    needs={}
    for mat in r['materials']:needs[mat['item_id']]=needs.get(mat['item_id'],0)+mat['count']*count
    allocations=[]
    for mid,number in needs.items():
        for index,item in sorted(inv['items'].items(),key=lambda x:int(x[0])):
            if item['item_id']!=mid or item.get('locked'):continue
            # Do not consume strengthened/embedded/custom equipment as ingredients.
            if item.get('enhance_level',0) or item.get('magic_spar',0) or item.get('beat_level',0):continue
            use=min(number,available(inv,index),255)
            if use:allocations.append({'index':int(index),'item_id':mid,'count':use,'before':item['count'],'serial':item.get('serial')});number-=use
            if not number:break
        if number:raise ProtocolError(item_name(mid)+'材料不足；目前只使用背包材料，不拆用已擺家具或雜物櫃')
    if len(allocations)>255:raise ProtocolError('使用的背包格數過多')
    w=Writer().u16(tool).u16(item_id).u8(count).u8(len(allocations))
    for a in allocations:w.u8(a['index']).u8(a['count'])
    w.u16(0).u8(0) # no cabinet or placed furniture ingredients
    return r,allocations,Packet(64,1,w.build())

from wlre.services.items.crafting_plan import PlanMixin

class Crafting(PlanMixin):
    def __init__(self):self.pending=None;self.next_start=False;self.seen_completed=0;self.wait_output=None

    @writes('crafting')
    def _set_pending(self,state,action,now,**data):
        self.pending={'action':action,'due':now+15,**data};state.crafting['pending']=action;state.crafting['status']='已送出，等待伺服器確認'

    @writes('crafting')
    def _clear(self,state,confirmed=True):
        if confirmed:reservations.release(state.inventory,'crafting')
        else:reservations.uncertain(state.inventory,'crafting')
        self.pending=None;state.crafting['pending']=None

    @writes('crafting')
    def _server_command(self,state,command,now=None):
        now=time.monotonic() if now is None else now;action=command.get('action');c=state.crafting
        if action=='stop_auto':c['auto_continue']=False;c['status']='已停止自動接續；已開始的伺服器製作仍需按暫停';return []
        if self.pending:raise ProtocolError('製作操作尚待伺服器確認，請勿重複操作')
        if c['uncertain']:raise ProtocolError('製作狀態不確定，請重新登入同步後再操作')
        if action=='enter':
            if state.battle.get('active') or state.event_flow.get('blocked'):raise ProtocolError('請先結束戰鬥或事件')
            return [Packet(65,1,Writer().u32(state.player['role_id']).build())]
        if action=='pause':
            c['auto_continue']=False
            if not c['running']:raise ProtocolError('目前沒有正在製作的項目')
            packet=Packet(64,3,bytes([c['active']]))
        else:
            if state.battle.get('active') or state.event_flow.get('blocked'):raise ProtocolError('等待戰鬥／事件結束後再操作製作')
            pause=coordination_reason(state,'crafting')
            if pause:raise ProtocolError(pause)
            if action=='add':
                r,allocations,packet=recipe_plan(state,int(command['item_id']),command['count'])
                reservations.acquire(state.inventory,'crafting',allocations,exclusive=True)
                self._set_pending(state,'add',now,item_id=r['item_id'],allocations=allocations,ack=False,quick=r['seconds']==0,quick_done=False)
                return [packet]
            if not c['ready']:raise ProtocolError('製作排程尚未同步')
            if action=='start':
                if not c['queue']:raise ProtocolError('製作排程為空')
                if c['running']:c.update(auto_continue=True,status='接管目前製作，完成後自動接續');return []
                row=c['queue'].get('1');r=RECIPES.get(str(row['item_id'])) if row else None
                if not r:raise ProtocolError('首項製作配方未知，無法確認設備')
                tool=tool_for(state,r['tool_id'])
                # Use the server-assigned craft NPC, never select an arbitrary follower.
                packet=Packet(64,2,Writer().u16(tool).u8(row['index']).u8(c['human_index']).u32(c['human_id']).build())
                c['auto_continue']=True
            elif action in ('delete','up','down'):
                if c['running']:raise ProtocolError('請先暫停製作，再調整排程')
                index=int(command['index'])
                if str(index) not in c['queue']:raise ProtocolError('排程已變更，請重新選取')
                if command.get('revision')!=c['revision']:raise ProtocolError('排程已更新，請重新選取')
                if action=='delete':packet=Packet(64,4,bytes([index]))
                else:
                    other=index+(-1 if action=='up' else 1)
                    if str(other) not in c['queue']:raise ProtocolError('已位於排程邊界')
                    packet=Packet(64,6,bytes([index,other]))
            else:raise ProtocolError('未知製作操作')
        self._set_pending(state,action,now);return [packet]

    @writes('crafting')
    def _server_observe(self,event,state,now=None):
        now=time.monotonic() if now is None else now;k=event['type'];c=state.crafting
        if k=='craft_completed' and c['completed']>self.seen_completed:
            self.seen_completed=c['completed']
            self.next_start=bool(c['auto_continue'])
            pending=self.pending or {}
            self.wait_output={'item_id':pending.get('output_item'),'required':pending.get('output_count',1),'received':pending.get('output_received',0),'due':now+15}
            if pending.get('action')=='complete':self._clear(state)
        if k=='craft_failed':self._clear(state);self.next_start=False
        output=(self.pending if self.pending and self.pending['action']=='complete' else self.wait_output)
        if output is not None:
            wanted=output.get('output_item',output.get('item_id'));number=0
            if k=='bag_add' and event['item']['item_id']==wanted:number=event['item']['count']
            elif event.get('room_action')=='add' and event['furniture']['item_id']==wanted and (event.get('kind')==2 or state.furniture['current_owner']==state.player.get('role_id')):number=1
            elif event.get('room_action')=='tool' and event.get('kind')==1 and event['item_id']==wanted and state.furniture['current_owner']==state.player.get('role_id'):number=1
            field='output_received' if 'action' in output else 'received'
            output[field]=output.get(field,0)+number
        p=self.pending
        if p and p['action']=='add':
            if k=='craft_added' and event['row']['item_id']==p['item_id']:p['ack']=True
            if k=='craft_completed' and p['quick'] and not p['quick_done']:
                p.update(ack=True,quick_done=True);c['completed']+=1;self.seen_completed=c['completed']
            if p['ack']:
                consumed=bool(state.inventory.get('reliable'))
                for a in p['allocations']:
                    item=state.inventory['items'].get(str(a['index']))
                    if item and (item['item_id']!=a['item_id'] or item.get('serial')!=a['serial'] or item['count']>a['before']-a['count']):consumed=False
                    if item is None and a['before']>a['count']:consumed=False
                if consumed:self._clear(state);c['status']='排程與材料扣除均已確認'
        elif p and ((p['action']=='start' and k=='craft_started') or (p['action']=='pause' and k=='craft_paused') or (p['action']=='delete' and k=='craft_deleted') or (p['action'] in ('up','down') and k=='craft_swapped')):self._clear(state)

    @writes('crafting')
    def _server_tick(self,state,now=None):
        now=time.monotonic() if now is None else now;c=state.crafting
        if self.pending and now>=self.pending['due']:
            if self.pending['action']=='add':state.inventory['reliable']=False
            self._clear(state,confirmed=False);c.update(auto_continue=False,uncertain=True,status='製作回覆逾時，停止重送；請重新登入同步');return []
        if self.pending or not c['auto_continue'] or c['uncertain']:return []
        if coordination_reason(state,'crafting'):return []
        if c['running'] and not c['completion_requested']:
            row=c['queue'].get(str(c['active']))
            if not row:return []
            real_time=effective_time(state,row)
            if real_time is None:c['status']='等待自家家具／製作夥伴資料，尚不能確認製作時間';return []
            if elapsed(c,row,now)>real_time:
                recipe=RECIPES.get(str(row['item_id']))
                if not recipe:c['status']='製作配方未知，未自動送出完成請求';return []
                c['completion_requested']=True
                self._set_pending(state,'complete',now,inventory_revision=state.inventory['revision'],room_revision=state.furniture['revision'],output_item=row['item_id'],output_count=recipe['output']*row['count'],output_received=0)
                return [Packet(64,10)]
        if self.next_start and not c['running']:
            if not self.wait_output or self.wait_output['received']<self.wait_output['required']:
                if self.wait_output and now>=self.wait_output['due']:
                    self.next_start=False;c.update(auto_continue=False,status='製作已完成，但未確認完整產物，停止自動接續')
                return []
            self.wait_output=None
            self.next_start=False
            if not c['queue']:
                if not self.plan(state)['enabled']:c['auto_continue']=False;c['status']='全部製作完成'
                return []
            try:return self.command(state,{'action':'start'},now)
            except ProtocolError as exc:c['auto_continue']=False;c['status']=str(exc)
        return []

    @writes('crafting')
    def disconnect(self,state):
        if self.pending and self.pending['action']=='add':state.inventory['reliable']=False
        self.plan(state).update(enabled=False,status='連線已結束，請確認剩餘清單後重新啟動')
        self._clear(state,confirmed=False);self.next_start=False;self.wait_output=None;state.crafting.update(auto_continue=False,status='連線已結束，重新登入後同步伺服器排程')
