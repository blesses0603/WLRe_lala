"""Room.IsInHouseScene checks FurSysSceneNum, not all current scenes."""
from wlre.paths import RESOURCE_ROOT
from functools import lru_cache
import json

# Lua/Common/Define.lua FurSysSceneNum, checked by Room.IsInHouseScene.
HOUSE_SCENES=frozenset((10299,10298,10000))

@lru_cache(maxsize=1)
def known_scenes():
    data=json.loads(RESOURCE_ROOT.joinpath('stage_coordinates.json').read_text(encoding='utf-8'))
    return frozenset(int(x) for x in data['stages'])


def house_scene(scene):
    """True = known house; False = known ordinary scene; None = unknown."""
    if scene is None:return None
    try:scene=int(scene)
    except (TypeError,ValueError):return None
    if scene in HOUSE_SCENES:return True
    return False if scene in known_scenes() else None


def affects_navigation(event,scene):
    if not event.get('affects_geometry',True):return False
    if event.get('geometry_scope')=='house':return house_scene(scene) is not False
    return True


