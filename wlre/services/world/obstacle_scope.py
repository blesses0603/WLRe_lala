"""Room.IsInHouseScene checks FurSysSceneNum, not all current scenes."""

# Lua/Common/Define.lua FurSysSceneNum, checked by Room.IsInHouseScene.
HOUSE_SCENES=frozenset((10299,10298,10000))



def house_scene(scene):
    """True = known house; False = known ordinary scene; None = unknown."""
    if scene is None:return None
    try:scene=int(scene)
    except (TypeError,ValueError):return None
    from wlre.services.world.house_navigation import HOUSE_MIN,HOUSE_MAX,instance_aliases
    if scene in HOUSE_SCENES or HOUSE_MIN<=scene<=HOUSE_MAX:return True
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    runtime=current_runtime()
    if runtime is not None:
        stages=runtime.stages
        if scene in stages:return False
        if 61501<=scene<=62000:
            try:return False if scene in instance_aliases(stages) else None
            except ValueError:return None
        return None
    # No current catalog means unknown, even before the first sync attempt.
    # A house-scoped change must therefore conservatively invalidate navigation.
    return None


def affects_navigation(event,scene):
    if not event.get('affects_geometry',True):return False
    if event.get('geometry_scope')=='house':return house_scene(scene) is not False
    return True


