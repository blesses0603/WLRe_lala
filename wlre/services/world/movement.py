"""Local path locomotion and C6-1 position reporting, not server arrival ACKs."""
import math
from wlre.services.world.coordinates import Coordinates
from wlre.services.world.navigation import Repository
from wlre.network.protocol import walk
from wlre.network.wire import ProtocolError
from wlre.services.battle.party import own_team


class Movement:
    interval=0.2
    speed=3500.0  # Int3 / second; Define.lua WalkSpeed=3.5, world scale=1000.

    def __init__(self,converter=None,repository=None):
        self.converter=converter
        self.repository=repository
        self.active=False
        self.points=[]
        self.index=1
        self.position=None
        self.next_due=0.0

    def start(self,state,x,y,now,bounds=None):
        if not (0<=x<=65535 and 0<=y<=65535):raise ProtocolError('目的地超出 UInt16 座標範圍')
        if state.activities:raise ProtocolError('目前'+ '、'.join(state.activities)+'中，無法移動')
        team=own_team(state)
        if team and team['leader_id']!=state.player.get('role_id'):raise ProtocolError('隊員跟隨隊長，請先離隊')
        if state.battle.get('active'):raise ProtocolError('戰鬥中無法移動')
        if state.event_flow.get('blocked'):
            if str(state.event_flow.get('last_source','')).startswith('C20-8'):
                raise ProtocolError('傳點請求正在等待伺服器回覆；未收到事件回覆時，15 秒後解除本機等待')
            raise ProtocolError('伺服器事件流程尚未結束：'+str(state.event_flow.get('last_source'))+'；等待事件結束 S20-8')
        fix=state.location.get('confirmed')
        if not fix or not state.player.get('role_id'):raise ProtocolError('尚無本機起點座標，不能規劃移動')
        scene=state.player['scene']
        if fix['scene']!=scene:raise ProtocolError('起點與角色地圖不同')
        if state.navigation.get('stale') and state.navigation.get('scene')==scene:
            raise ProtocolError('目前場景的動態障礙尚未重建，暫停導航：'+', '.join(state.navigation.get('reasons',[])))
        local=state.local_movement
        if (local and local.get('scene')==scene and local.get('role_id')==state.player['role_id']
                and local.get('base_fix_packet')==fix['packet_number']):
            start=(local['x'],local['y'])
            start_height=local.get('nav_height')
        elif state.location.get('confirmed_is_current'):
            start=(fix['x'],fix['y']);start_height=None
        else:raise ProtocolError('起點位置不明：先前座標同步沒有本機定位或可續用的推算位置')
        self.converter=self.converter or Coordinates()
        self.repository=self.repository or Repository()
        route=self.converter.route(self.repository,scene,start,(x,y),start_height=start_height)
        points=[tuple(p) for p in route['points']]
        # Validate the complete path before replacing an active movement.
        if not points or any(not all(math.isfinite(v) for v in p) for p in points):
            raise ProtocolError('無效的導航路徑')
        for p in points:
            px,py=self.converter.to_packet(scene,p[0],p[2])
            if not (0<=px<=65535 and 0<=py<=65535):raise ProtocolError('導航路徑超出封包座標範圍')
        if bounds is not None:
            cx,cy,radius=bounds
            if math.hypot(x-cx,y-cy)>radius+1e-6:raise ProtocolError('徘徊終點超出固定範圍')
            for point in points:
                px,py=self.converter.to_packet(scene,point[0],point[2])
                if math.hypot(px-cx,py-cy)>radius+1e-6:
                    raise ProtocolError('導航路徑會離開徘徊範圍，重新選點')
        self.points=points;self.position=points[0];self.index=1
        self.scene=scene;self.role_id=state.player['role_id'];self.revision=state.navigation.get('revision')
        self.next_due=now+self.interval
        self.active=len(points)>1
        self.last_packet=(round(start[0]),round(start[1]))
        state.local_movement={'status':'running' if self.active else 'finished',
            'scene':scene,'role_id':self.role_id,'x':start[0],'y':start[1],
            'nav_height':points[0][1],'base_fix_packet':fix['packet_number'],
            'target':{'scene':scene,'x':x,'y':y,'source':'local_goal','packet_number':state.packet_count},
            'speed_world':3.5,'interval':self.interval,'steps_sent':0,
            'reason':'沿導航路徑推算；伺服器尚未確認抵達','path_points':len(points)}
        state.movement_check={'status':'waiting','target':dict(state.local_movement['target']),
                              'role_id':self.role_id,'confirmation':None}
        return route

    def stop(self,state,reason='使用者停止'):
        self.active=False
        if state.local_movement:
            state.local_movement={**state.local_movement,'status':'stopped','reason':reason}

    def observe(self,event,state):
        if not self.active:return
        kind=event['type']
        if kind=='world_player' or (kind=='position_snapshot' and event['role_id']==self.role_id):
            self.stop(state,'收到本機定位或校正，停止舊路徑')
        elif kind in ('battle_start','battle_units') and state.battle.get('active'):
            self.stop(state,'進入戰鬥，停止移動')
        elif (kind=='walk' and event['role_id']==self.role_id
                and (event['x'],event['y'])!=self.last_packet):
            self.stop(state,'收到本機伺服器移動通知，停止本機路徑以待核對')
        elif kind=='movement_stop':self.stop(state,'收到伺服器停止通知')
        elif state.navigation.get('stale') and state.navigation.get('scene')==self.scene:
            self.stop(state,'障礙資料變更，停止舊路徑')

    def tick(self,state,now):
        if not self.active:return []
        if (state.player.get('role_id')!=self.role_id or state.player.get('scene')!=self.scene
                or state.battle.get('active') or state.event_flow.get('blocked')
                or state.navigation.get('revision')!=self.revision
                or state.navigation.get('stale')):
            self.stop(state,'角色、場景、戰鬥或導航狀態改變');return []
        if now+1e-9<self.next_due:return []
        # No catch-up burst after a blocked loop; each report advances at most one period.
        self.next_due=now+self.interval
        budget=self.speed*self.interval
        while self.index<len(self.points):
            end=self.points[self.index];distance=math.dist(self.position,end)
            if distance<=budget+1e-8:
                self.position=end;self.index+=1;budget=max(0,budget-distance)
            else:
                ratio=budget/distance
                self.position=tuple(a+(b-a)*ratio for a,b in zip(self.position,end));break
        finished=self.index==len(self.points)
        x,y=self.converter.to_packet(self.scene,self.position[0],self.position[2])
        xy=(round(x),round(y))
        self.active=not finished
        local=state.local_movement
        state.local_movement={**local,'x':x,'y':y,'nav_height':self.position[1],
            'status':'finished' if finished else 'running',
            'reason':'本機路徑已走完；尚無伺服器位置確認' if finished else '沿導航路徑推算；尚非伺服器確認'}
        if xy==self.last_packet:return []
        self.last_packet=xy
        state.local_movement['steps_sent']+=1
        return [walk(*xy)]
