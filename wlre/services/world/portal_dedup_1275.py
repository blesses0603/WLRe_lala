"""P3: remove duplicate 1275 UI portals, not distinct official routes.

An Eve door index has meaning only within its source scene. Name, target,
or XY collisions alone do not prove duplicate transport events: one entry
can represent several different doors or arrival points.
This module never edits authenticated source data or grants C20-8.
"""

from wlre.services.world.catalog_source_policy import is_official_revision
from collections import Counter


def display_destination(portal):
    """Known destination identity for display grouping, never a packet index."""
    if portal.get('destination_verified') is True:
        target = portal.get('destination')
    elif portal.get('reference_destination_defined') is True:
        target = portal.get('reference_destination_scene_id')
    elif portal.get('kind') == 'link' and portal.get('hidden_destination_defined') is True:
        target = portal.get('hidden_destination_scene_id')
    elif not is_official_revision(portal.get('source_revision')):
        target = portal.get('destination')
    else:
        return None
    return target if type(target) is int and 0 < target <= 65535 else None


def collapse_portal_destinations(rows):
    """One visible point per source/destination; retain the actual chosen row.

    Prefer a usable door, then a verified target and official label. Remaining
    ties use the real source ID for stable selection. The catalog and its
    alternative positions are not changed or converted into synthetic IDs.
    """
    result, groups = [], {}
    def rank(row):
        index = row.get('index')
        return (not bool(row.get('direct_eligible')),
                row.get('destination_verified') is not True,
                not bool(row.get('official_name')),
                index if type(index) is int else 65536,
                str(row.get('id','')))
    for row in rows:
        target = display_destination(row)
        if target is None:
            result.append(row)
            continue
        key = (row.get('scene'), target)
        if key not in groups:
            groups[key] = len(result)
            result.append(row)
        elif rank(row) < rank(result[groups[key]]):
            result[groups[key]] = row
    return result


def deduplicate_1275_portals(scene_rows):
    """Return (display rows, audit) with ambiguous repeated IDs disabled.

    If one scene exposes the same ordinary door index twice, keep a single
    diagnostic row but revoke its transmission/navigation privileges. Hidden
    markers are removed only when source grid, destination and NameID all
    match; their synthetic H indexes are then rebuilt per source scene.
    """
    cleaned = {}
    info = {
        'duplicate_event_id_removed': 0,
        'duplicate_hidden_removed': 0,
        'ambiguous_event_ids': [],
        'repeated_name_groups': 0,
        'repeated_coordinate_groups': 0,
    }
    for raw_scene, candidates in scene_rows.items():
        scene = int(raw_scene) if isinstance(raw_scene, str) and raw_scene.isdecimal() else raw_scene
        if type(scene) is not int or not isinstance(candidates, list):
            continue
        used = {}
        hidden_ids = set()
        result = []
        for portal in candidates:
            if not isinstance(portal, dict) or not is_official_revision(portal.get('source_revision')):
                result.append(portal)
                continue
            kind, idx = portal.get('kind'), portal.get('index')
            if kind == 'door' and type(idx) is int and idx > 0:
                key = ('door', idx)
                if key in used:
                    previous = result[used[key]]
                    # One ambiguous Eve event ID is never a valid packet index,
                    # even if the two UI rows happen to be identical.
                    previous.update(
                        direct_eligible=False, direct_door_index=None,
                        door_index=None, destination=None,
                        destination_verified=False,
                        navigation_status='unverified',
                        coordinate_valid=False, x=None, y=None,
                        projection_guard=None, link_reference_only=True)
                    previous['name'] = '傳點 #' + str(idx) + '（門事件 ID 重複，待核對）'
                    previous['direct_note'] = '同一場景出現重複門事件 ID，已停止換圖與導航，請檢查正式來源'
                    previous['reference_issues'] = tuple(dict.fromkeys(
                        tuple(previous.get('reference_issues') or ())
                        + ('duplicate_eve_door',)))
                    info['duplicate_event_id_removed'] += 1
                    if (scene, idx) not in info['ambiguous_event_ids']:
                        info['ambiguous_event_ids'].append((scene, idx))
                    continue
                used[key] = len(result)
            elif kind == 'link' and isinstance(idx, str) and idx.startswith('H'):
                # Require every strong field; unknown positions are not
                # sufficiently identified to discard a portal.
                x, y = portal.get('source_grid_x'), portal.get('source_grid_y')
                target = portal.get('hidden_destination_scene_id')
                name_id = portal.get('name_id')
                if all(type(v) is int for v in (x, y, target, name_id)):
                    key = (x, y, target, name_id)
                    if key in hidden_ids:
                        info['duplicate_hidden_removed'] += 1
                        continue
                    hidden_ids.add(key)
                ordinal = 1 + sum(
                    row.get('kind') == 'link' and
                    isinstance(row.get('index'), str) and row['index'].startswith('H')
                    for row in result if isinstance(row, dict))
                portal['index'] = f'H{ordinal}'
                portal['id'] = f'1275-hidden:{scene}:{ordinal}'
            result.append(portal)
        # Shared labels or screen positions can be intentional and never
        # collapse two different source event indices or destinations.
        names = Counter(
            row['official_name'].strip() for row in result
            if isinstance(row, dict) and type(row.get('official_name')) is str
            and row['official_name'].strip())
        points = Counter(
            (row['x'], row['y']) for row in result
            if isinstance(row, dict) and row.get('coordinate_valid') is True
            and type(row.get('x')) is int and type(row.get('y')) is int)
        info['repeated_name_groups'] += sum(n > 1 for n in names.values())
        info['repeated_coordinate_groups'] += sum(n > 1 for n in points.values())
        cleaned[str(scene)] = result
    info['ambiguous_event_ids'].sort()
    return cleaned, info
