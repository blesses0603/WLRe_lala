"""Guard portal destinations; retain known exits when the current map has no image."""
from functools import lru_cache
from wlre.services.world.smallmaps import SmallMaps

@lru_cache(maxsize=1)
def smallmaps():
    return SmallMaps()

def destination_problem(portal, maps=None):
    # A 1275 graph edge is not a validated server trigger, irrespective of
    # whether its destination has a SmallMap2D texture.
    if portal.get('source_revision') == 1275:
        return '1275 場景連結僅供查閱，A*導航網格、門索引與伺服器條件尚未驗證'
    maps = maps if maps is not None else smallmaps()
    destination = portal.get('destination')
    if destination is None:
        return '傳點目的地尚未確認，已停用以避免進入無法預覽的場景。'
    if not maps.has_image(destination):
        return '傳點目的地沒有原始小地圖，已停用此入口。'
    return None

def allowed_rows(catalog, scene, maps, recovery=False):
    if catalog.data.get('source_revision') == 1275:
        # Display the real 1275 destination names as read-only references.
        # destination_problem() keeps all actions disabled.
        return catalog.for_scene(scene)
    return [p for p in catalog.for_scene(scene)
            if destination_problem(p, maps) is None
            and (not recovery or p.get('direct_eligible'))]
