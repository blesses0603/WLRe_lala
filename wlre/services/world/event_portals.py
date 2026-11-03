"""Resolve physical exits from same-version Eve PlayerTouch → Convey records.

No quest state is invented and no conditions are executed locally. Conditional
routes keep every possible target; the existing single-request transport waits
for the server's authoritative map update.
"""
from collections import Counter


def reconcile_event_portals(doors, stages, positions, destinations):
    from wlre.services.world.boundary_portals import touch_bounds, door_anchor
    from wlre.services.world.portal_evidence_1275 import _projection_guard
    for scene, entries in doors.items():
        stage = stages.get(scene, {})
        guard = _projection_guard(stage)
        if guard is None:
            continue
        counts = Counter(d['index'] for d in entries)
        for door in entries:
            key = (scene, door['index'])
            if door.get('portal_resolution_issue'):
                continue
            if counts[door['index']] != 1 or not 1 <= door['index'] <= 65535:
                continue
            events = door.get('touch_event_records') or []
            transfers = [t for e in events for t in e.get('convey_transfers', [])]
            if any(e.get('missing_convey_ids') for e in events):
                positions.pop(key, None)
                destinations.pop(key, None)
                continue
            if not transfers:
                continue
            targets = {t['destination'] for t in transfers}
            if (any(e.get('missing_convey_ids') for e in events)
                    or any(not 0 < t <= 65535 or t not in stages for t in targets)):
                # The independent event source invalidates a claimed fixed route.
                positions.pop(key, None)
                destinations.pop(key, None)
                continue
            bounds = touch_bounds(door, stage)
            if bounds is None and door.get('sign_type') in (1,4):
                # Some official boundaries are lines (zero width/height).
                # Keep their exact geometry, without inventing an area.
                anchor = door_anchor(door, stage)
                rx, ry = stage.get('pos_x_ratio'), stage.get('pos_y_ratio')
                if anchor and type(rx) is int and type(ry) is int:
                    right = (door['right']-1)*20*rx + door['sign_x']*rx
                    bottom = (door['bottom']-1)*20*ry + door['sign_y']*ry
                    if 0 <= anchor[0] <= right <= 65535 and 0 <= anchor[1] <= bottom <= 65535:
                        bounds = (*anchor, right, bottom)
            point = ((bounds[0]+bounds[2])//2, (bounds[1]+bounds[3])//2) if bounds else (
                door_anchor(door, stage) if door.get('sign_type') in (2,3,5) else None)
            if point is None or not (0 <= point[0] <= 65535 and 0 <= point[1] <= 65535):
                continue
            previous = destinations.get(key, {})
            if (previous.get('destination') is not None
                    and previous['destination'] not in targets):
                positions.pop(key, None)
                destinations.pop(key, None)
                door['portal_resolution_issue'] = 'conflicting_event_destination'
                continue
            target = next(iter(targets)) if len(targets) == 1 else None
            # Keep a proven route point when it is within this exact door.
            position = positions.get(key)
            if position is None:
                positions[key] = dict(scene=scene, index=door['index'], x=point[0], y=point[1],
                    position_verified=True, projection_guard=guard,
                    source_kind='eve_convey_door_scaled', trigger_bounds=bounds,
                    binding_kind='eve_convey', link_index=None)
            destinations[key] = dict(previous, scene=scene, index=door['index'],
                destination=target, destination_verified=target is not None,
                event_x=door['x'], event_y=door['y'], matched_touch_region=True,
                door_binding_verified=True, trigger_verified=False,
                event_convey_verified=True, event_decided_only=target is None,
                destination_candidates=sorted(targets), convey_transfers=transfers,
                binding_kind='eve_convey', link_index=previous.get('link_index'))
