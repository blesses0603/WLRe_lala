"""Local path locomotion and C6-1 position reporting, not server arrival ACKs."""
from wlre.core.state_ownership import writes
import math
from wlre.network.protocol import walk
from wlre.network.wire import ProtocolError
from wlre.services.battle.party import own_team
from wlre.services.world.dynamic_bundle_runtime import current_catalog_token


class Movement:
    interval=0.2
    speed=3500.0  # Int3 / second; Define.lua WalkSpeed=3.5, world scale=1000.

    def __init__(self,converter=None,repository=None):
        self.converter=converter
        self.repository=repository
        self.active=False
        self.official_execution=False
        self.execution_interrupted=False
        self.catalog_token=current_catalog_token()
        self.points=[]
        self.index=1
        self.position=None
        self.next_due=0.0

    @writes('movement')
    def start(self,state,x,y,now,bounds=None,max_distance=None):
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
        from wlre.services.world.house_navigation import require_general_navigation
        try:require_general_navigation(scene=scene)
        except ValueError as error:raise ProtocolError(str(error)) from error
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
        token=current_catalog_token()
        from wlre.services.world.official_movement import OfficialMovementAdapter
        if self.converter is None:
            self.converter=OfficialMovementAdapter()
            self.repository=self.converter
        official=isinstance(self.converter,OfficialMovementAdapter)
        if official and not self.converter.is_current():
            self.converter=OfficialMovementAdapter(runtime_getter=self.converter.runtime_getter,root=self.converter.repository.root)
            self.repository=self.converter
        if official:
            route=self.converter.route(self.repository,scene,start,(x,y),start_height=start_height,
                                       navigation_state=state.navigation)
            self.converter.validate_route(route)
        else:
            if self.repository is None:raise ProtocolError('缺少已確認的導航來源')
            route=self.converter.route(self.repository,scene,start,(x,y),start_height=start_height)
            if route.get('can_send_packets') is not True or route.get('live_movement_verified') is not True:
                raise ProtocolError('路徑尚未具備實際移動驗證與授權，僅供預覽，不能用於角色移動。')
        points=[tuple(p) for p in route['points']]
        # Validate the complete path before replacing an active movement.
        if not points or any(not all(math.isfinite(v) for v in p) for p in points):
            raise ProtocolError('無效的導航路徑')
        for p in points:
            px,py=self.converter.to_packet(scene,p[0],p[2])
            if not (0<=px<=65535 and 0<=py<=65535):raise ProtocolError('導航路徑超出封包座標範圍')
        if official:
            if (not math.isfinite(now) or not 0<self.speed<=3500 or self.interval<0.2
                    or not math.isfinite(self.interval) or len(points)>512):
                raise ProtocolError('官方受限移動的速度／頻率／路徑上限無效')
            length=sum(math.dist(a,b) for a,b in zip(points,points[1:]))
            limit=20000 if max_distance is None else min(20000,float(max_distance))
            if not math.isfinite(limit) or limit<=0 or length>limit:
                raise ProtocolError('官方受限移動路徑超出單段距離上限')
        if bounds is not None:
            if (not isinstance(bounds,(tuple,list)) or len(bounds)!=3
                    or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds) or bounds[2]<=0):
                raise ProtocolError('徘徊距離範圍無效')
            cx,cy,radius=bounds
            if math.hypot(x-cx,y-cy)>radius+1e-6:raise ProtocolError('徘徊終點超出固定範圍')
            for point in points:
                px,py=self.converter.to_packet(scene,point[0],point[2])
                if math.hypot(px-cx,py-cy)>radius+1e-6:
                    raise ProtocolError('導航路徑會離開徘徊範圍，重新選點')
        if current_catalog_token()!=token:
            raise ProtocolError('規劃途中官方資源已更新，請重新選點。')
        self.official_execution=official
        self.execution_interrupted=False
        self.execution_bounds=bounds
        self.execution_deadline=now+min(30, max(3,length/self.speed+5)) if official else None
        self.sent_position=points[0]
        self.base_fix_packet=fix['packet_number']
        self.route_id=getattr(self,"route_id",0)+1
        self.catalog_token=token
        self.points=points;self.position=points[0];self.index=1
        self.scene=scene;self.role_id=state.player['role_id'];self.revision=state.navigation.get('revision')
        self.next_due=now+self.interval
        self.active=len(points)>1
        self.last_packet=(round(start[0]),round(start[1]))
        state.local_movement={'status':'running' if self.active else 'finished',
            'scene':scene,'role_id':self.role_id,'x':start[0],'y':start[1],
            'nav_height':points[0][1],'base_fix_packet':fix['packet_number'],
            'catalog_token':token,'navigation_revision':self.revision,'route_id':self.route_id,
            'target':{'scene':scene,'x':x,'y':y,'source':'local_goal','packet_number':state.packet_count},
            'speed_world':3.5,'interval':self.interval,'steps_sent':0,
            'reason':'沿導航路徑推算；伺服器尚未確認抵達','path_points':len(points)}
        if official:state.local_movement.update(execution_policy='bounded_official_land',live_movement_verified=False,runtime_collision_verified=False)
        state.movement_check={'status':'waiting','target':dict(state.local_movement['target']),
                              'role_id':self.role_id,'confirmation':None}
        return route

    @writes('movement')
    def stop(self,state,reason='使用者停止',*,requires_restart=False):
        self.active=False
        if requires_restart and self.official_execution:self.execution_interrupted=True
        if state.local_movement:
            state.local_movement={**state.local_movement,'status':'stopped','reason':reason}

    @writes('movement')
    def observe(self,event,state):
        kind=event['type']
        if not self.active:
            if self.official_execution and (kind in ('world_player','movement_stop')
                    or (kind in ('position_snapshot','walk') and event.get('role_id')==getattr(self,'role_id',None)
                        and (kind=='position_snapshot' or (event.get('x'),event.get('y'))!=getattr(self,'last_packet',None)))):
                self.stop(state,'收到伺服器校正／停止，需重新規劃',requires_restart=True)
            return
        if kind=='world_player' or (kind=='position_snapshot' and event['role_id']==self.role_id):
            self.stop(state,'收到本機定位或校正，停止舊路徑',requires_restart=True)
        elif kind in ('battle_start','battle_units') and state.battle.get('active'):
            self.stop(state,'進入戰鬥，停止移動')
        elif (kind=='walk' and event['role_id']==self.role_id
                and (event['x'],event['y'])!=self.last_packet):
            self.stop(state,'收到本機伺服器移動通知，停止本機路徑以待核對',requires_restart=True)
        elif kind=='movement_stop':self.stop(state,'收到伺服器停止通知',requires_restart=True)
        elif state.navigation.get('stale') and state.navigation.get('scene')==self.scene:
            self.stop(state,'障礙資料變更，停止舊路徑',requires_restart=True)

    @writes('movement')
    def tick(self,state,now):
        if not self.active:return []
        if current_catalog_token()!=self.catalog_token:
            self.stop(state,'官方資源已更新，請重新選點移動',requires_restart=True);return []
        if (state.player.get('role_id')!=self.role_id or state.player.get('scene')!=self.scene
                or state.battle.get('active') or state.event_flow.get('blocked')
                or state.navigation.get('revision')!=self.revision
                or state.navigation.get('stale')):
            self.stop(state,'角色、場景、戰鬥或導航狀態改變',requires_restart=not(state.battle.get('active') or state.event_flow.get('blocked')));return []
        if self.official_execution:
            if (not isinstance(state.local_movement,dict)
                    or (state.location.get('confirmed') or {}).get('packet_number')!=self.base_fix_packet):
                self.stop(state,'位置狀態已改變或不明，需重新規劃',requires_restart=True);return []
            if (not math.isfinite(now) or now>self.execution_deadline or not 0<self.speed<=3500
                    or not math.isfinite(self.interval) or self.interval<0.2
                    or state.local_movement.get('steps_sent',0)>=128):
                self.stop(state,'受限移動逾時或超出速度／步數限制',requires_restart=True);return []
            try:
                if not self.converter.is_current():raise ValueError('官方資料已變更')
            except (ValueError,OSError):
                self.stop(state,'官方導航來源已失效',requires_restart=True);return []
        if now+1e-9<self.next_due:return []
        # No catch-up burst after a blocked loop; each report advances at most one period.
        self.next_due=now+self.interval
        budget=self.speed*self.interval
        if self.official_execution:budget=max(0,min(700,budget)-15)  # Reserve packet rounding error.
        position=self.position;index=self.index
        while index<len(self.points):
            end=self.points[index];distance=math.dist(position,end)
            if distance<=budget+1e-8:
                position=end;index+=1;budget=max(0,budget-distance)
                if self.official_execution:break  # Never report a chord across a corner.
            else:
                ratio=budget/distance
                position=tuple(a+(b-a)*ratio for a,b in zip(position,end));break
        finished=index==len(self.points)
        try:
            x,y=self.converter.to_packet(self.scene,position[0],position[2]);xy=(round(x),round(y))
            if self.official_execution:
                nx,nz=self.converter.to_navigation(self.scene,*xy);sent=(nx,position[1],nz)
                self.converter.validate_step(self.sent_position,sent)
                if not all(0<=v<=65535 for v in xy) or math.dist(self.sent_position,sent)>700.000001:
                    raise ValueError('發送步距超出上限')
                if self.execution_bounds is not None:
                    cx,cy,radius=self.execution_bounds
                    if math.hypot(xy[0]-cx,xy[1]-cy)>radius+1e-6:raise ValueError('發送座標超出徘徊範圍')
        except (ValueError,OSError,KeyError,TypeError) as error:
            self.stop(state,'官方受限移動停止：'+str(error),requires_restart=True);return []
        self.position=position;self.index=index;self.active=not finished
        local=state.local_movement
        state.local_movement={**local,'x':xy[0] if self.official_execution else x,
            'y':xy[1] if self.official_execution else y,'nav_height':position[1],
            'status':'finished' if finished else 'running',
            'reason':'本機路徑已走完；尚無伺服器位置確認' if finished else '沿導航路徑推算；尚非伺服器確認'}
        if xy==self.last_packet:return []
        if self.official_execution:self.sent_position=sent
        self.last_packet=xy
        state.local_movement['steps_sent']+=1
        return [walk(*xy)]
