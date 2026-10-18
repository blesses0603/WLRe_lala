"""Guard portal destinations; retain known exits when the current map has no image."""
from functools import lru_cache
from wlre.services.world.smallmaps import SmallMaps

@lru_cache(maxsize=1)
def smallmaps():
    return SmallMaps()

def destination_problem(portal, maps=None):
    maps = maps if maps is not None else smallmaps()
    destination = portal.get('destination')
    if destination is None:
        return '傳點目的地尚未確認，已停用以避免進入無法預覽的場景。'
    if not maps.has_image(destination):
        return '傳點目的地沒有原始小地圖，已停用此入口。'
    return None

def allowed_rows(catalog, scene, maps, recovery=False):
    return [p for p in catalog.for_scene(scene)
            if destination_problem(p, maps) is None
            and (not recovery or p.get('direct_eligible'))]
