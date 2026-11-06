"""Diagnostic-only comparison. No downloader, session or movement dependency."""
import copy
import math

from wlre.services.world.coordinates import Coordinates
from wlre.services.world.dynamic_bundle_runtime import current_runtime
from wlre.services.world.house_navigation import require_general_navigation
from wlre.services.world.navigation import Repository
from wlre.services.world.navigation_preview import PreviewRepository
from wlre.services.world.navigation_preview_job import signature


def _xy(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('Expected two packet coordinates')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 65535 for v in value):
        raise ValueError('Invalid packet coordinates')
    return tuple(float(v) for v in value)


def _summary(route, *, official, catalog_key):
    if official and (route.get('can_send_packets') is not False or route.get('catalog_key') != catalog_key):
        raise ValueError('Official preview lacks matching provenance or movement prohibition')
    points = route.get('packet_points_xy_float')
    if not isinstance(points, (list, tuple)) or not 1 <= len(points) <= 4096:
        raise ValueError('Invalid or excessive diagnostic point count')
    points = [_xy(p) for p in points]
    return dict(status='ready', can_send_packets=False, diagnostic_xy=points,
                point_count=len(points), xy_length=sum(math.dist(a, b) for a, b in zip(points, points[1:])))


def compare(map_id, start, end, *, travel_mode='land', runtime_getter=current_runtime,
            state_getter=lambda: {}, coordinates_factory=Coordinates,
            legacy_factory=Repository, official_factory=PreviewRepository):
    """Use loaded versioned DB only; caller supplies live getters to detect expiry.

    Old geometry ignores travel tags. Equality is descriptive, never acceptance.
    Results intentionally have no movement-route points or authority.
    """
    if type(map_id) is not int or not 1 <= map_id <= 65535:
        raise ValueError('Invalid map ID')
    start, end = _xy(start), _xy(end)
    if travel_mode not in ('land', 'sea', 'sky'):
        raise ValueError('Invalid travel mode')
    require_general_navigation(scene=map_id)
    runtime = runtime_getter()
    if runtime is None:
        raise ValueError('Verified official runtime required')
    identity = runtime.catalog_identity
    stages = copy.deepcopy(runtime.stages)
    state = copy.deepcopy(state_getter())
    key = signature(state)
    navigation = state.get('navigation', {})
    if navigation.get('stale'):
        raise ValueError('Navigation state is stale')
    require_general_navigation(model=stages.get(map_id, {}).get('model_id'))
    report = dict(status='incomplete', can_send_packets=False, live_movement_verified=False,
                  catalog_key=identity.key, map_id=map_id, travel_mode=travel_mode,
                  limitations=['Legacy geometry ignores travel tags and original flags.',
                               'Costs, heights and runtime obstacles are not compared.',
                               'Matching XY points do not establish official runtime equivalence.'])

    def stale():
        now = runtime_getter()
        return (now is not runtime or now.catalog_identity != identity or
                now.stages != stages or signature(state_getter()) != key)

    for name in ('legacy', 'official'):
        if stale():
            return {k: v for k, v in {**report, 'status': 'stale'}.items() if k not in ('legacy', 'official')}
        try:
            if name == 'legacy':
                coordinates = coordinates_factory()
                # Retain existing checks and additionally bind legacy metadata to this snapshot.
                stage, _, _ = coordinates.mapping(map_id)
                current = stages.get(map_id)
                fields = ('model_id', 'map_width', 'map_height', 'small_offset_x', 'small_offset_y')
                if current is None or any(stage.get(f) != current.get(f) for f in fields):
                    raise ValueError('Legacy stage differs from official snapshot')
                route = coordinates.route(legacy_factory(), map_id, start, end)
            else:
                route = official_factory(identity, stages).route(
                    map_id, start, end, download=False, travel_mode=travel_mode,
                    smooth=False, navigation_state=copy.deepcopy(navigation))
            value = _summary(route, official=name == 'official', catalog_key=identity.key)
        except Exception as error:
            value = dict(status='error', can_send_packets=False, error=str(error)[:300] or type(error).__name__)
        if stale():
            return {k: v for k, v in {**report, 'status': 'stale'}.items() if k not in ('legacy', 'official')}
        report[name] = value
    if all(report[n]['status'] == 'ready' for n in ('legacy', 'official')):
        old, new = report['legacy'], report['official']
        report.update(status='compared', exact_xy_sequence_match=old['diagnostic_xy'] == new['diagnostic_xy'],
                      xy_length_delta=new['xy_length'] - old['xy_length'])
    return report
