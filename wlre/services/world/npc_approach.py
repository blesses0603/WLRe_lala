"""Manual approach to an authenticated NPC's nearby walkable point."""
import math

from wlre.network.wire import ProtocolError
from wlre.services.world.catalog_source_policy import official_runtime
from wlre.services.world.display_position import current_position
from wlre.services.world.dynamic_bundle_runtime import current_catalog_token
from wlre.services.world.navigation import NavigationError

# Stage.TransferPosition uses 0.01 world units per packet coordinate. Stop
# around one world unit away; the server still decides interaction distance.
NEAR_DISTANCE = 100


def approach(state, movement, command, now):
    if state.phase!='world_ready' or not state.player.get('role_id'):
        raise ProtocolError('請先完成角色與世界資料同步')
    scene=command.get('scene');index=command.get('npc_index');npc_id=command.get('npc_id')
    if type(scene) is not int or scene!=state.player.get('scene'):
        raise ProtocolError('NPC 不在角色目前地圖，請重新選取')
    if type(index) is not int or type(npc_id) is not int:
        raise ProtocolError('NPC 身分或索引無效')
    if state.battle.get('active') or state.event_flow.get('blocked') or state.activities:
        raise ProtocolError('請先結束戰鬥或事件，再移動至 NPC')
    token=current_catalog_token()
    runtime=official_runtime('npc')
    matches=[row for row in runtime.npc_index.for_scene(scene)
             if row.get('index')==index and row.get('npc_id')==npc_id]
    if len(matches)!=1:raise ProtocolError('NPC 已不在目前官方資料中，請重新選取')
    npc=matches[0];stage=runtime.stages.get(scene,{})
    rx,ry=stage.get('pos_x_ratio'),stage.get('pos_y_ratio')
    if (type(rx) is not int or type(ry) is not int
            or not 1<=rx<=255 or not 1<=ry<=255
            or type(npc.get('x')) is not int or type(npc.get('y')) is not int):
        raise ProtocolError('NPC 官方座標或場景倍率尚未核對')
    # Data.LoadEve scales NewNpc common XY by the scene ratios.
    x,y=npc['x']*rx,npc['y']*ry
    if not 0<=x<=65535 or not 0<=y<=65535:raise ProtocolError('NPC 位置超出遊戲座標範圍')
    position=current_position(state.snapshot())
    if position is None or not position.get('filled') or position['scene']!=scene:
        raise ProtocolError('角色目前位置尚未確認，無法前往 NPC')
    if current_catalog_token()!=token:raise ProtocolError('官方資料已更新，請重新選取 NPC')
    dx,dy=position['x']-x,position['y']-y
    if math.hypot(dx,dy)<=NEAR_DISTANCE:
        movement.stop(state,'已在 NPC 附近')
        return
    angle=math.atan2(dy,dx)
    # Try the player-facing side first; a wall or counter may require another
    # approach. Movement.start validates a complete connected path before it
    # replaces movement, and no packets are sent while testing candidates.
    for radius in (NEAR_DISTANCE,60,140):
        for turn in (0,1,-1,2,-2,3,-3,4):
            theta=angle+turn*math.pi/4
            target=(round(x+radius*math.cos(theta)),round(y+radius*math.sin(theta)))
            if any(not 0<=v<=65535 for v in target):continue
            if current_catalog_token()!=token:raise ProtocolError('官方資料已更新，請重新選取 NPC')
            try:
                movement.start(state,*target,now)
                if current_catalog_token()!=token:
                    movement.stop(state,'官方資料已更新，已停止舊 NPC 路徑')
                    raise ProtocolError('官方資料已更新，請重新選取 NPC')
                return
            except NavigationError:
                continue
    raise ProtocolError('NPC 附近找不到可到達的導航位置')
