"""AutoPlay.lua AutoWalk/ReAutoWalk four offsets, native order and no dwell."""
from wlre.network.wire import ProtocolError
from wlre.services.world.coordinates import Coordinates
from wlre.services.battle.party import own_team

OFFSETS=((-2,-1),(-2,2),(2,-1),(2,2))
LABELS={'disabled':'已停止','ready':'準備徘徊','moving':'四點循環中','paused_battle':'遇戰暫停','paused_event':'等待事件結束','paused_navigation':'等待導航資料','paused_scene':'地圖已改變','paused_team':'隊員跟隨隊長','manual':'手動移動後重新定位','blocked':'路線不可達'}

def origin(state):
    fix=state.location.get('confirmed')
    pid=state.player.get('role_id');scene=state.player.get('scene')
    if not fix or not pid or fix['scene']!=scene:raise ProtocolError('尚無本機地圖與起點座標')
    local=state.local_movement
    if (local and local.get('role_id')==pid and local.get('scene')==scene
            and local.get('base_fix_packet')==fix['packet_number']):return local['x'],local['y']
    if state.location.get('confirmed_is_current'):return fix['x'],fix['y']
    raise ProtocolError('尚無可續用的本機位置，請先取得本機定位')

class Roaming:
    def __init__(self,converter=None):
        self.converter=converter;self.enabled=False;self.sticky=False
        self.await_battle_end=False;self.current_path=0;self.manual=False

    def status(self,state,value,reason='',**fields):
        updated={**state.roaming,'status':value,'reason':reason,**fields}
        if updated!=state.roaming:state.roaming=updated

    def start(self,state,movement,now=0):
        if state.activities:raise ProtocolError('目前'+ '、'.join(state.activities)+'中，不能啟動徘徊')
        self.center=origin(state);self.scene=state.player['scene'];self.role_id=state.player['role_id']
        self.converter=self.converter or getattr(movement,'converter',None) or Coordinates()
        self.converter.mapping(self.scene)
        movement.stop(state,'切換為原版四點徘徊')
        self.enabled=True;self.sticky=False;self.manual=False
        self.await_battle_end=bool(state.battle.get('active') or state.event_flow.get('blocked'))
        state.roaming={'enabled':True,'status':'ready','reason':'依 Lua 四點順序循環',
            'scene':self.scene,'role_id':self.role_id,'center':list(self.center),
            'next_point':self.current_path+1,'goals_started':0,'target':None,'mode':'lua_four_points'}

    def stop(self,state,movement,reason='使用者停止徘徊'):
        self.enabled=False;self.sticky=False;self.await_battle_end=False;self.manual=False
        movement.stop(state,reason);self.status(state,'disabled',reason,enabled=False)

    def recenter(self,state,movement,reason='依目前位置重新定位'):
        movement.stop(state,reason)
        self.center=origin(state);self.manual=False;self.sticky=False
        self.status(state,'ready',reason,center=list(self.center))

    def observe(self,event,state,movement):
        if not self.enabled:return
        if state.activities:
            self.stop(state,movement,'目前'+ '、'.join(state.activities)+'中，依原版停止徘徊');return
        if state.player.get('role_id')!=self.role_id:
            self.stop(state,movement,'登入角色改變，已停止徘徊');return
        if state.player.get('scene')!=self.scene:
            self.stop(state,movement,'地圖改變，請在新地圖啟動徘徊');return
        kind=event['type']
        if kind=='battle_start':
            self.await_battle_end=True;movement.stop(state,'遇戰暫停徘徊');self.status(state,'paused_battle','等待戰後事件結束')
        elif kind=='event_end':
            self.await_battle_end=False
            self.status(state,'ready','戰後接續原本四點順序，保留中心')
        elif kind=='position_snapshot' and event['role_id']==self.role_id:
            # Movement.observe already stopped the old route. A fresh server fix
            # overrides the old local simulation before ReAutoWalk recenters.
            expected=getattr(movement,'last_packet',None)
            state.local_movement=None
            if self.manual or self.sticky or (event['x'],event['y'])!=expected:self.recenter(state,movement,'依伺服器確認位置重新定位')
        elif kind=='walk' and event['role_id']==self.role_id and (event['x'],event['y'])!=getattr(movement,'last_packet',None):
            # S6-1 is a destination notice, not arrival. Never recenter from it.
            self.sticky=True;self.status(state,'paused_event','收到不同移動目的地，等待伺服器位置確認')

    def tick(self,state,movement,now):
        if not self.enabled:return
        if state.activities:
            self.stop(state,movement,'目前'+ '、'.join(state.activities)+'中');return
        team=own_team(state)
        if team and team['leader_id']!=self.role_id:
            movement.stop(state,'隊員跟隨隊長');self.status(state,'paused_team','隊員不可自行徘徊');return
        if state.player.get('role_id')!=self.role_id or state.player.get('scene')!=self.scene:
            self.stop(state,movement,'角色或地圖已改變');return
        if self.sticky:return
        if state.navigation.get('stale'):
            movement.stop(state,'導航障礙資料已失效');self.status(state,'paused_navigation','等待障礙資料更新');return
        if state.battle.get('active') or self.await_battle_end:
            self.status(state,'paused_battle','等待戰後事件結束');return
        if state.maintenance.get('pending') or state.maintenance.get('uncertain') or state.maintenance.get('checking') or state.event_flow.get('blocked') or state.inventory.get('field_supply',{}).get('pending') or state.inventory.get('field_supply',{}).get('uncertain') or state.auto_battle.get('status') in ('healing','waiting_heal'):
            self.status(state,'paused_event','等待事件／補給完成');return
        if movement.active:
            self.status(state,'manual' if self.manual else 'moving','抵達後接續下一點');return
        if self.manual:
            if not state.local_movement or state.local_movement.get('status')!='finished':
                self.status(state,'paused_event','手動移動中斷，等待位置確認');return
            self.recenter(state,movement,'手動移動完成，以目前位置作為新中心')
        dx,dz=OFFSETS[self.current_path]
        nx,nz=self.converter.to_navigation(self.scene,*self.center)
        x,y=self.converter.to_packet(self.scene,nx+dx*1000,nz+dz*1000)
        point=self.current_path+1;self.current_path=(self.current_path+1)%4
        try:movement.start(state,round(x),round(y),now)
        except (ValueError,OSError,KeyError) as exc:
            self.sticky=True;self.status(state,'blocked','原版第'+str(point)+'點不可達：'+str(exc));return
        self.status(state,'moving','依原版順序前往第'+str(point)+'點',
            target={'scene':self.scene,'x':round(x),'y':round(y)},next_point=self.current_path+1,
            goals_started=state.roaming['goals_started']+1)


def summary(value):
    text=LABELS.get(value.get('status'),'尚未啟動');center=value.get('center')
    if center:text+=f"｜中心 ({round(center[0])}, {round(center[1])})｜下一點 {value.get('next_point',1)}/4"
    reason=value.get('reason','').replace('依伺服器確認位置重新定位','依目前位置重新定位').replace('等待伺服器位置確認','等待位置更新')
    return text+('｜'+reason if reason else '')
