"""All-scene cross-reference audit of authenticated portal sources; read-only."""
from collections import Counter
import struct
from wlre.services.world.portal_links_1275 import parse_stage_map_portals, parse_eve_door_links


def audit_portal_coverage(doors, stages, stage_raw=None, link_raw=None,
                        positions=None, destinations=None, names=None):
    """Only call after official source verification; never authorize a packet.

    Include scenes without doors and orphaned marker/link indices. An Eve event
    container without a StageMap marker is not automatically a missing exit.
    """
    positions, destinations, names = positions or {}, destinations or {}, names or {}
    markers, links, marker_counts = {}, {}, Counter()
    statuses = {'StageMapData_C': 'missing', 'EveDoorLinks': 'missing'}
    for table, raw, reader in (
            ('StageMapData_C', stage_raw, parse_stage_map_portals),
            ('EveDoorLinks', link_raw, parse_eve_door_links)):
        if raw is None: continue
        try:
            parsed = reader(raw)
            if table == 'StageMapData_C':
                markers = parsed
                for offset in range(4, len(raw), 18):
                    scene, kind, cross, index, x, y, name, order = struct.unpack_from('<HBHIHHIB', raw, offset)
                    if kind in (2, 3) and scene and index:
                        marker_counts[scene, index] += 1
            else: links = parsed
            statuses[table] = 'parsed'
        except (ValueError, TypeError):
            statuses[table] = 'invalid'
    expected_scenes = set(stages)
    all_scenes = expected_scenes | set(doors) | set(links) | {scene for scene, _ in marker_counts}
    for rows in links.values(): all_scenes.update(row['destination'] for row in rows)
    by_scene = {}
    for (scene, index), row in markers.items(): by_scene.setdefault(scene, {})[index] = row
    rows = []
    for scene in sorted(all_scenes):
        events = doors.get(scene, ())
        counts = Counter(row['index'] for row in events if isinstance(row, dict) and type(row.get('index')) is int)
        stage_markers = by_scene.get(scene, {})
        scene_links = {row['index']: row for row in links.get(scene, ())}
        indices = set(counts) | {index for sid, index in marker_counts if sid == scene} | set(scene_links)
        details, gaps, ordinary = [], 0, 0
        for index in sorted(indices):
            marker = stage_markers.get(index)
            reasons = []
            if marker_counts[scene, index] > 1: reasons.append('duplicate_stage_marker')
            # Hidden portals have different semantics, not ordinal links.
            kind = marker.get('kind') if marker else None
            if kind == 3:
                category = 'hidden_portal'
            elif marker_counts[scene, index] == 0 and index not in scene_links:
                category = 'event_container_only' if statuses['StageMapData_C'] == 'parsed' else 'source_incomplete'
            else:
                category = 'ordinary_portal'
                ordinary += 1
                if marker_counts[scene, index] == 0: reasons.append('missing_stage_marker')
                if counts[index] == 0: reasons.append('missing_eve_door')
                elif counts[index] != 1: reasons.append('duplicate_eve_door')
                link = scene_links.get(index)
                if not link: reasons.append('missing_door_link')
                elif link['destination'] not in expected_scenes: reasons.append('unknown_destination_scene')
                if (scene, index) not in positions: reasons.append('position_unverified')
                if (scene, index) not in destinations: reasons.append('destination_unverified')
            gaps += bool(reasons)
            details.append({'index': index, 'category': category, 'issues': reasons,
                            'named': (scene, index) in names})
        rows.append({'scene': scene, 'in_scene_table': scene in expected_scenes,
                     'eve_doors': sum(counts.values()), 'ordinary_portals': ordinary,
                     'unresolved': gaps, 'details': details})
    complete = all(value == 'parsed' for value in statuses.values())
    return {'source_revision': 1275, 'source_status': statuses,
            'all_sources_available': complete, 'scene_count': len(rows),
            'scene_table_count': len(expected_scenes), 'scenes': rows,
            'unresolved_portals': sum(row['unresolved'] for row in rows),
            'can_send_packets': False, 'live_transfer_verified': False}
