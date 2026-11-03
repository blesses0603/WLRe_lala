"""Guard portal destinations; retain known exits when the current map has no image."""

from wlre.services.world.catalog_source_policy import is_official_revision
from functools import lru_cache
from wlre.services.world.smallmaps import SmallMaps

@lru_cache(maxsize=1)
def smallmaps():
    return SmallMaps()

def stage_marker_has_no_target(portal):
    """Kind 2 has no target; Kind 3 EvtID=0 explicitly leaves it undeclared."""
    return (portal.get('stage_marker_kind')==2 or
            portal.get('stage_marker_kind')==3
            and type(portal.get('stage_marker_event_id')) is int
            and portal['stage_marker_event_id']==0)


def stage_marker_trigger(portal):
    """Explicit verified-door mode for a labeled marker with no declared target."""
    return (is_official_revision(portal.get('source_revision'))
            and portal.get('stage_marker_only') is True
            and portal.get('door_binding_verified') is True
            and portal.get('direct_eligible') is True
            and stage_marker_has_no_target(portal)
            and portal.get('destination') is None
            and type(portal.get('direct_door_index')) is int
            and 1<=portal['direct_door_index']<=65535
            and portal.get('coordinate_valid') is True
            and type(portal.get('official_name')) is str
            and bool(portal['official_name'].strip()))


def destination_problem(portal, maps=None):
    if is_official_revision(portal.get('source_revision')):
        # Same-revision sources must identify the actual physical door. A
        # StageMap-only trigger can leave its target for the server to decide.
        verified = (
            portal.get('destination_verified') is True
            and portal.get('direct_eligible') is True
            and type(portal.get('direct_door_index')) is int
            and 1 <= portal['direct_door_index'] <= 65535
            and type(portal.get('destination')) is int
            and 0 < portal['destination'] <= 65535)
        if not verified and not stage_marker_trigger(portal) and not event_decided_trigger(portal):
            return ('1275 門事件的目的地或觸碰索引尚未完成交叉核對；'
                    '不會送出傳點指令。')
        return None
    destination = portal.get('destination')
    if destination is None:
        return '傳點目的地尚未確認。'
    return None

def allowed_rows(catalog, scene, maps, recovery=False):
    # 1275 Eve NewDoor index/positions are authenticated independently of
    # the still-unverified destination and server trigger. Show them as
    # non-actionable markers instead of hiding all doors from the minimap.
    if (is_official_revision(getattr(catalog, 'data', {}).get('source_revision'))):
        return [p for p in catalog.for_scene(scene)
                if is_official_revision(p.get('source_revision'))]
    return [p for p in catalog.for_scene(scene)
            if destination_problem(p, maps) is None
            and (not recovery or p.get('direct_eligible'))]


def event_decided_trigger(portal):
    """A physical Eve door with several decoded conditional destinations."""
    return (portal.get('event_decided_only') is True
            and portal.get('event_convey_verified') is True
            and portal.get('door_binding_verified') is True
            and portal.get('direct_eligible') is True
            and portal.get('coordinate_valid') is True
            and type(portal.get('direct_door_index')) is int
            and 1 <= portal['direct_door_index'] <= 65535
            and portal.get('destination') is None
            and bool(portal.get('destination_candidates')))
