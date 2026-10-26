"""Guard portal destinations; retain known exits when the current map has no image."""
from functools import lru_cache
from wlre.services.world.smallmaps import SmallMaps

@lru_cache(maxsize=1)
def smallmaps():
    return SmallMaps()

def destination_problem(portal, maps=None):
    if portal.get('source_revision') == 1275:
        # Same-revision Eve, StageMap and EveDoorLinks must agree on the door,
        # position and destination. A name alone never unlocks C20-8.
        verified = (
            portal.get('destination_verified') is True
            and portal.get('direct_eligible') is True
            and type(portal.get('direct_door_index')) is int
            and 1 <= portal['direct_door_index'] <= 65535
            and type(portal.get('destination')) is int
            and 0 < portal['destination'] <= 65535)
        if not verified:
            return ('1275 門事件的目的地或觸碰索引尚未完成交叉核對；'
                    '不會送出傳點指令。')
        maps = maps if maps is not None else smallmaps()
        if not maps.has_image(portal['destination']):
            return '1275 目的地缺少已確認小地圖，拒絕直接傳送。'
        return None
    maps = maps if maps is not None else smallmaps()
    destination = portal.get('destination')
    if destination is None:
        return '傳點目的地尚未確認，已停用以避免進入無法預覽的場景。'
    if not maps.has_image(destination):
        return '傳點目的地沒有原始小地圖，已停用此入口。'
    return None

def allowed_rows(catalog, scene, maps, recovery=False):
    # 1275 Eve NewDoor index/positions are authenticated independently of
    # the still-unverified destination and server trigger. Show them as
    # non-actionable markers instead of hiding all doors from the minimap.
    if (getattr(catalog, 'data', {}).get('source_revision') == 1275):
        return [p for p in catalog.for_scene(scene)
                if p.get('source_revision') == 1275]
    return [p for p in catalog.for_scene(scene)
            if destination_problem(p, maps) is None
            and (not recovery or p.get('direct_eligible'))]
