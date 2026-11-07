"""Room.IsInHouseScene checks FurSysSceneNum, not all current scenes."""
from wlre.paths import RESOURCE_ROOT
from functools import lru_cache

# Lua/Common/Define.lua FurSysSceneNum, checked by Room.IsInHouseScene.
HOUSE_SCENES=frozenset((10299,10298,10000))

@lru_cache(maxsize=1)
def known_scenes():
    from wlre.storage.bundled_database import load_bundled_json
    data=load_bundled_json('stage_coordinates.json', root=RESOURCE_ROOT)
    return frozenset(int(x) for x in data['stages'])


def house_scene(scene):
    """True = known house; False = known ordinary scene; None = unknown."""
    if scene is None:return None
    try:scene=int(scene)
    except (TypeError,ValueError):return None
    from wlre.services.world.house_navigation import HOUSE_MIN,HOUSE_MAX,instance_aliases
    if scene in HOUSE_SCENES or HOUSE_MIN<=scene<=HOUSE_MAX:return True
    from wlre.services.world.dynamic_bundle_runtime import current_runtime,dynamic_attempted
    runtime=current_runtime()
    if runtime is not None:
        stages=runtime.stages
        if scene in stages:return False
        if 61501<=scene<=62000:
            try:return False if scene in instance_aliases(stages) else None
            except ValueError:return None
        return None
    # Failed current synchronization must not consult a stale bundled catalog.
    if dynamic_attempted():return None
    return False if scene in known_scenes() else None


def affects_navigation(event,scene):
    if not event.get('affects_geometry',True):return False
    if event.get('geometry_scope')=='house':return house_scene(scene) is not False
    return True


