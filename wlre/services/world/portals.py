"""Versioned exits from EveDoorLinks, StageMapData and DoorLinkData."""
from wlre.paths import RESOURCE_ROOT
import json
import math
from pathlib import Path
from wlre.services.world.scene_names_1275 import source_scene_label
from wlre.services.world.portal_inspection_1275 import link_inspection_fields
from wlre.services.world.portal_dedup_1275 import deduplicate_1275_portals



def portal_source_diagnostic(status):
    """Show an actionable, sanitized reason for missing 1275 names/positions."""
    hints = {
        'asset_missing_from_manifest': '官方 Manifest 未列出傳點名稱資產',
        'bundle_not_cached': '官方傳點 Bundle 尚未下載；重啟 LaLa 執行官方同步',
        'bundle_integrity_failed': '傳點 Bundle 校驗不符，已拒絕使用',
        'textasset_extract_failed': '傳點 Bundle 已找到，但 TextAsset 解包失敗',
        'stage_map_invalid': '傳點名稱表二進位格式尚未通過驗證',
        'layout_unrecognized': '門連線資料未通過格式解析，請查看下方具體診斷；尚不能判定新版欄位已變更',
        'download_budget_exhausted': '傳點資料下載超過安全額度，已保留既有功能',
        'bundle_sync_failed': '官方傳點資料同步失敗，尚未取得正式內容',
        'missing_stage_map': '尚未取得官方 StageMapData 傳點名稱表',
        'core_runtime_unavailable': '1275 核心資料尚未完成驗證',
        'legacy_portals_disabled': '目前僅使用 1275 官方傳點；1262 舊清單已停用，請確認官方版本與同步',
    }
    if type(status) is not str:
        return '尚無 1275 傳點名稱載入狀態'
    if status in hints:
        return hints[status]
    if status.startswith('destination_links_'):
        reason = status.removeprefix('destination_links_')
        return ('官方傳點名稱表已可用；門連線資料：'
                + hints.get(reason, '目的地資料尚未通過驗證'))
    if status in ('stage_map_ready', 'destination_links_loaded'):
        return '官方傳點資料已載入，部分入口仍可能沒有名稱 ID'
    return '1275 傳點資料狀態待核對'



class Portals:
    def __init__(self,path=None):
        if path is None:
            from wlre.services.world.runtime_1275 import baseline_revision, active_runtime
            # The desktop client is 1275-only. An older revision is NOT a
            # reason to fall through to the tracked 1262 portals.json file.
            # Keep that legacy file solely for explicit fixture/audit reads.
            revision = baseline_revision()
            if revision != '1275':
                self.data = {
                    'portals': {}, 'audit': [], 'entities': {},
                    'source_revision': 1275, 'source_ready': False,
                    'portal_metadata_status': 'legacy_portals_disabled',
                    'portal_duplicate_report': {},
                }
                self.audit = {}
                return
            if revision == '1275':
                # The verified 1275 Eve table includes a door index and its
                # local coordinates, but not an audited destination or proof
                # that C20-8 is safe on this server. Expose the original
                # positions as read-only map markers; NEVER reuse 1262 routes.
                source_ready = False
                doors = {}
                duplicate_report = {}
                scene_names = {}
                door_count = 0
                coverage = {}
                try:
                    verified = active_runtime()
                    coverage = getattr(verified, 'portal_coverage', {})
                    if not isinstance(coverage, dict): coverage = {}
                    # Only names bound to this exact verified 1275 runtime are
                    # permitted. Legacy map_names.json is NOT a name fallback.
                    scene_names = getattr(verified, 'scene_names', {})
                    if not isinstance(scene_names, dict):
                        scene_names = {}
                    linked = getattr(verified, 'portal_destinations', {})
                    if not isinstance(linked, dict):
                        linked = {}
                    display_targets = getattr(
                        verified, 'portal_display_destinations', {})
                    if not isinstance(display_targets, dict):
                        display_targets = {}
                    portal_names = getattr(verified, 'portal_names', {})
                    if not isinstance(portal_names, dict):
                        portal_names = {}
                    portal_positions = getattr(verified, 'portal_positions', {})
                    if not isinstance(portal_positions, dict):
                        portal_positions = {}
                    portal_evidence = getattr(verified, 'portal_link_evidence', {})
                    if not isinstance(portal_evidence, dict):
                        portal_evidence = {}
                    portal_extra_routes = getattr(verified, 'portal_extra_routes', [])
                    if not isinstance(portal_extra_routes, list):
                        portal_extra_routes = []
                    portal_stage_markers = getattr(verified, 'portal_stage_markers', [])
                    if not isinstance(portal_stage_markers, list):
                        portal_stage_markers = []
                    portal_texts = getattr(verified, 'texts', {})
                    if not isinstance(portal_texts, dict):
                        portal_texts = {}
                    portal_metadata_status = getattr(
                        verified, 'portal_metadata_status', 'missing_stage_map')
                    portal_schema_report = getattr(
                        verified, 'portal_schema_report', {})
                    if not isinstance(portal_schema_report, dict):
                        portal_schema_report = {}
                    door_count = sum(len(rows) for rows in verified.doors.values())
                    for scene, entries in verified.doors.items():
                        if (type(scene) is int and 0 <= scene <= 65535):
                            scene_id = scene
                        elif (isinstance(scene, str) and scene.isdecimal()
                              and 0 <= int(scene) <= 65535):
                            scene_id = int(scene)
                        else:
                            continue
                        scene_label = source_scene_label(scene_id, scene_names)
                        visible = []
                        for row in entries:
                            if not isinstance(row, dict):
                                continue
                            index, x, y = (row.get('index'), row.get('x'),
                                           row.get('y'))
                            if (type(index) is not int or not 0 <= index <= 65535
                                    or type(x) is not int or type(y) is not int
                                    or not 0 <= x <= 4294967295
                                    or not 0 <= y <= 4294967295):
                                continue
                            # Eve.NewDoor's common x/y are EVENT GRID data,
                            # not the position used in official UIMain
                            # _SetPortalPosition. Rendering them as packet XY
                            # previously placed portals on the wrong part of
                            # the minimap. Only EveDoorLinks + StageData ratios
                            # may supply an actionable projection.
                            position = portal_positions.get((scene_id, index))
                            if not isinstance(position, dict):
                                position = {}
                            map_x, map_y = position.get('x'), position.get('y')
                            valid_xy = (
                                position.get('position_verified') is True
                                and position.get('source_kind')
                                == '1275_eve_door_links_grid_scaled'
                                and position.get('scene') == scene_id
                                and position.get('index') == index
                                and type(map_x) is int and type(map_y) is int
                                and 0 <= map_x <= 65535 and 0 <= map_y <= 65535)
                            strict_valid_xy = valid_xy
                            reference = portal_evidence.get((scene_id, index), {})
                            if not isinstance(reference, dict):
                                reference = {}
                            inspection = link_inspection_fields(
                                reference, scene_id, index, scene_names)
                            reference_xy = (
                                reference.get('source_kind') ==
                                '1275_eve_door_links_reference'
                                and reference.get('scene') == scene_id
                                and reference.get('index') == index
                                and reference.get('position_verified') is True
                                and isinstance(reference.get('projection_guard'), dict)
                                and type(reference.get('x')) is int
                                and type(reference.get('y')) is int)
                            if not valid_xy and reference_xy:
                                map_x, map_y = reference['x'], reference['y']
                                valid_xy = True
                            link = linked.get((scene_id, index), {})
                            if not isinstance(link, dict):
                                link = {}
                            destination = link.get('destination')
                            verified_target = (
                                link.get('matched_stage_map') is True
                                and link.get('destination_verified') is True
                                and link.get('trigger_verified') is False
                                and type(destination) is int
                                and 0 < destination <= 65535
                                and link.get('event_x') == x and link.get('event_y') == y)
                            destination = destination if verified_target else None
                            target_label = (source_scene_label(destination, scene_names)
                                            if verified_target else '目的地未確認')
                            # Door indices are internal event IDs, not
                            # geographical or destination names. Never present
                            # an event label as the name of a scene.
                            # Lua/UIMain first uses StageMapData.NameID and
                            # only falls back to the destination stage's name.
                            # A verified marker label is useful even when the
                            # separate EveDoorLinks route cannot be resolved.
                            official_name = portal_names.get((scene_id, index))
                            if (type(official_name) is not str
                                    or not official_name.strip()):
                                official_name = None
                            display_scene = display_targets.get((scene_id, index))
                            if (type(display_scene) is not int
                                    or not 0 < display_scene <= 65535):
                                display_scene = None
                            if (display_scene is None
                                    and reference.get('source_kind') ==
                                    '1275_eve_door_links_reference'
                                    and reference.get('scene') == scene_id
                                    and reference.get('index') == index
                                    and type(reference.get('destination')) is int
                                    and reference.get('destination_defined') is True):
                                display_scene = reference['destination']
                            display_label = (source_scene_label(
                                display_scene, scene_names)
                                if display_scene is not None else
                                target_label if verified_target else None)
                            # Display-only official linkage is NOT a verified
                            # C20-8 trigger. Even a named target cannot grant
                            # direct_eligible or supply packet event indices.
                            label = (official_name or
                                     ('前往 ' + display_label + '（連線名稱參考）'
                                      if display_label else
                                      '傳點 #' + str(index) +
                                      '（官方名稱未取得）'))
                            visible.append({
                                'id': f'1275:{scene_id}:{index}',
                                'scene': scene_id, 'index': index,
                                'name': label,
                                'official_name': official_name,
                                'display_destination_label': display_label,
                                'source_scene_label': scene_label,
                                'source_scene_name_known': scene_id in scene_names,
                                'destination_label': target_label,
                                'kind': 'door',
                                'source_revision': 1275,
                                'coordinate_valid': valid_xy,
                                'coordinate_source': (
                                    'verified_eve_door_links_scaled' if strict_valid_xy
                                    else 'official_link_reference_scaled' if reference_xy
                                    else 'unverified_event_grid'),
                                'projection_guard': (
                                    position.get('projection_guard') if strict_valid_xy
                                    else reference.get('projection_guard') if reference_xy
                                    else None),
                                'link_reference_only': bool(reference_xy and not strict_valid_xy),
                                **inspection,
                                'x': map_x if valid_xy else None,
                                'y': map_y if valid_xy else None,
                                'event_grid_x': x,
                                'event_grid_y': y,
                                'event_ids': tuple(row.get('event_ids') or ()),
                                'destination': destination,
                                'destination_verified': verified_target,
                                'direct_eligible': bool(verified_target and strict_valid_xy and 1 <= index <= 65535),
                                'direct_door_index': index if verified_target and strict_valid_xy and 1 <= index <= 65535 else None,
                                'door_index': index if verified_target and strict_valid_xy and 1 <= index <= 65535 else None,
                                'navigation_status': 'unverified',
                                'direct_note': (
                                    '1275 門編號／位置／目的地已交叉核對；可在手動確認後單次試傳，'
                                    '成功與否完全以伺服器回覆為準'
                                    if verified_target else
                                    '1275 傳點資料可列出，但來源格座標不可直接'
                                    '當成小地圖點位；需官方門連線和場景倍率核對，'
                                    '未驗證時不畫點也不送出換圖封包'),
                            })
                        doors[str(scene_id)] = visible
                    # EveDoorLinks can contain valid official links whose
                    # event has no NewDoor row. Display them as reference-only
                    # records. Their ordinal is NOT a verified C20-8 trigger.
                    for key, reference in sorted(portal_evidence.items()):
                        if (not isinstance(key, tuple) or len(key) != 2
                                or not isinstance(reference, dict)):
                            continue
                        scene_id, index = key
                        if (type(scene_id) is not int or type(index) is not int
                                or not 0 < scene_id <= 65535 or not 0 < index <= 65535
                                or reference.get('source_kind') !=
                                '1275_eve_door_links_reference'
                                or reference.get('scene') != scene_id
                                or reference.get('index') != index):
                            continue
                        existing = doors.setdefault(str(scene_id), [])
                        if any(row['index'] == index for row in existing):
                            continue
                        valid = (
                            reference.get('position_verified') is True
                            and isinstance(reference.get('projection_guard'), dict)
                            and type(reference.get('x')) is int
                            and type(reference.get('y')) is int)
                        inspection = link_inspection_fields(
                            reference, scene_id, index, scene_names)
                        target = reference.get('destination')
                        target_known = reference.get('destination_defined') is True
                        target_label = (source_scene_label(target, scene_names)
                                        if target_known else None)
                        official_name = portal_names.get(key)
                        if type(official_name) is not str or not official_name.strip():
                            official_name = None
                        label = (official_name or
                                 ('前往 ' + target_label + '（官方連線參考）'
                                  if target_label else
                                  '傳點 #' + str(index) + '（連線未完整驗證）'))
                        existing.append({
                            'id': f'1275-ref:{scene_id}:{index}',
                            'scene': scene_id, 'index': index,
                            'name': label, 'official_name': official_name,
                            'display_destination_label': target_label,
                            'source_scene_label': source_scene_label(
                                scene_id, scene_names),
                            'source_scene_name_known': scene_id in scene_names,
                            'destination_label': target_label or '目的地未確認',
                            'kind': 'door', 'source_revision': 1275,
                            'coordinate_valid': valid,
                            'coordinate_source': 'official_link_reference_scaled',
                            'projection_guard': (
                                reference.get('projection_guard') if valid else None),
                            'x': reference.get('x') if valid else None,
                            'y': reference.get('y') if valid else None,
                            'event_grid_x': None, 'event_grid_y': None,
                            'event_ids': (), 'destination': None,
                            'destination_verified': False,
                            'direct_eligible': False,
                            'direct_door_index': None, 'door_index': None,
                            'link_reference_only': True,
                            **inspection,
                            'navigation_status': 'unverified',
                            'direct_note': '官方連線僅供唯讀定位；沒有核對門事件，不允許送出傳送封包',
                        })
                    # HiddenPortalNew uses StageMap Kind=3 PositionX/Y and
                    # EvtID as its destination scene. This is NOT a normal
                    # Eve.NewDoor index and never enables C20-8.
                    hidden_by_scene = {}
                    for marker in portal_stage_markers:
                        if not isinstance(marker, dict) or marker.get('kind') != 3:
                            continue
                        scene_id = marker.get('scene')
                        if type(scene_id) is not int or not 0 < scene_id <= 65535:
                            continue
                        hidden_by_scene[scene_id] = hidden_by_scene.get(scene_id, 0) + 1
                        ordinal = hidden_by_scene[scene_id]
                        valid = (
                            marker.get('position_verified') is True
                            and isinstance(marker.get('projection_guard'), dict)
                            and type(marker.get('x')) is int
                            and type(marker.get('y')) is int)
                        target = marker.get('destination')
                        target_known = (
                            marker.get('destination_defined') is True
                            and type(target) is int and 0 < target <= 65535)
                        dest_label = (source_scene_label(target, scene_names)
                                      if target_known else None)
                        name = portal_texts.get(marker.get('name_id'))
                        if (type(name) is not str or not name.strip()
                                or len(name) > 160
                                or any(ord(ch) < 32 for ch in name)):
                            name = None
                        else:
                            name = name.strip()
                        doors.setdefault(str(scene_id), []).append({
                            'id': f'1275-hidden:{scene_id}:{ordinal}',
                            'scene': scene_id, 'index': f'H{ordinal}',
                            'name': (name or
                                     ('前往 ' + dest_label + '（隱藏傳點參考）'
                                      if dest_label else '隱藏傳點（目的地未確認）')),
                            'official_name': name,
                            'display_destination_label': dest_label,
                            'source_scene_label': source_scene_label(
                                scene_id, scene_names),
                            'source_scene_name_known': scene_id in scene_names,
                            'destination_label': dest_label or '目的地未確認',
                            'kind': 'link', 'source_revision': 1275,
                            'coordinate_valid': valid,
                            'coordinate_source': '1275_hidden_stage_marker',
                            'projection_guard': (
                                marker.get('projection_guard') if valid else None),
                            'x': marker.get('x') if valid else None,
                            'y': marker.get('y') if valid else None,
                            'event_grid_x': None, 'event_grid_y': None,
                            'event_ids': (), 'destination': None,
                            'destination_verified': False,
                            'direct_eligible': False, 'direct_door_index': None,
                            'door_index': None, 'navigation_status': 'unverified',
                            'link_reference_only': True,
                            'hidden_destination_scene_id': target,
                            'source_grid_x': marker.get('source_grid_x'),
                            'source_grid_y': marker.get('source_grid_y'),
                            'name_id': marker.get('name_id'),
                            'direct_note': '隱藏傳點僅供顯示。EvtID 是目的場景編號，不是 C20-8 門索引。',
                        })
                    doors, duplicate_report = deduplicate_1275_portals(doors)
                    source_ready = True
                except ValueError:
                    # During pre-login, verified files may not yet be installed.
                    # Retry from the UI when the map/scene is next refreshed.
                    pass
                self.data = {
                    'portals': doors, 'audit': [], 'entities': {},
                    'source_revision': 1275,
                    'door_count': door_count,
                    'official_link_reference_count': (len(portal_evidence) if source_ready else 0),
                    'official_route_reference_count': (len(portal_extra_routes) if source_ready else 0),
                    'official_route_references': (portal_extra_routes if source_ready else []),
                    'official_stage_marker_count': (len(portal_stage_markers) if source_ready else 0),
                    'official_stage_markers': (portal_stage_markers if source_ready else []),
                    'scene_names': scene_names,
                    'portal_metadata_status': (
                        portal_metadata_status if source_ready
                        else 'core_runtime_unavailable'),
                    'portal_schema_report': (
                        portal_schema_report if source_ready else {}),
                    'portal_name_count': sum(
                        bool(item.get('official_name')) for row in doors.values()
                        for item in row),
                    'destination_count': sum(
                        bool(item.get('destination_verified')) for row in doors.values()
                        for item in row),
                    'source_ready': source_ready,
                    'portal_coverage': coverage if source_ready else {},
                    'portal_duplicate_report': duplicate_report if source_ready else {},
                }
                self.audit = {}
                return
        self.data=json.loads((Path(path) if path else RESOURCE_ROOT.joinpath('portals.json')).read_text(encoding='utf8'))
        self.audit={r['scene']:r for r in self.data['audit']}

    def for_scene(self,scene):
        return self.data['portals'].get(str(scene),[])

    @staticmethod
    def label(portal):
        kind={'normal':'出口','event':'事件入口','link':'地圖連結',
              'door':'1275 傳點'}[portal['kind']]
        xy=f"({portal['x']}, {portal['y']})" if portal['coordinate_valid'] else '座標未確認'
        status='' if portal.get('navigation_status')=='endpoint_valid' else '｜無可用導航'
        return f"{portal['index']}. {portal['name']}｜{kind} {xy}{status}"

    @staticmethod
    def direct_target(portal,current_scene):
        if current_scene is None or current_scene != portal.get('scene'):
            raise ValueError('請切回角色目前地圖，才能直接觸發此出口。')
        index = portal.get('direct_door_index')
        if not portal.get('direct_eligible') or type(index) is not int or not 1 <= index <= 65535:
            raise ValueError(portal.get('direct_note','尚未確認此傳點的實際觸碰事件，未送出指令。'))
        return index

    @staticmethod
    def target(portal,current_scene):
        if current_scene!=portal['scene']:raise ValueError('請切回角色目前地圖，才能前往此傳送點。')
        if not portal['coordinate_valid']:raise ValueError('傳送點座標尚未確認。')
        if portal.get('navigation_status')!='endpoint_valid':raise ValueError(portal.get('navigation_note','此傳點沒有可用導航。'))
        points = portal.get('approach_points')
        x,y = points[0] if points else (portal['x'],portal['y'])
        return portal['scene'],x,y



def portal_map_pixel(portal, projection):
    """Only return portal position inside the matching 1024px map image.

    The verified flag represents a packet-space coordinate, not a raw
    Eve grid event. A stale/off-map marker is neither drawn nor clickable.
    """
    if not portal.get('coordinate_valid') or projection is None:
        return None
    x, y = portal.get('x'), portal.get('y')
    if (type(x) is not int or type(y) is not int
            or not 0 <= x <= 65535 or not 0 <= y <= 65535):
        return None
    expected = portal.get('projection_guard')
    if isinstance(expected, dict):
        # Do not project a 1275 position onto mismatched 1262 image geometry.
        for attr in ('rate', 'offset_x', 'offset_y', 'height'):
            value = expected.get(attr)
            actual = getattr(projection, attr, None)
            if (not isinstance(value, (int, float))
                    or not isinstance(actual, (int, float))
                    or not math.isfinite(value)
                    or not math.isfinite(actual)
                    or not math.isclose(value, actual, abs_tol=1e-6)):
                return None
    u, v = projection.packet_to_pixel(x, y)
    if not (math.isfinite(u) and math.isfinite(v)
            and 0 <= u <= 1024 and 0 <= v <= 1024):
        return None
    return (u, v)


def marked_portals(rows, projection):
    """Minimap list mirrors labeled markers; the full catalog stays auditable."""
    return [row for row in rows if row.get('source_revision') != 1275 or (
        bool(row.get('official_name') or row.get('display_destination_label'))
        and portal_map_pixel(row, projection) is not None)]


def nearest_marker(rows,projection,screen,event_x,event_y,radius=12):
    hits=[]
    for p in rows:
        point = portal_map_pixel(p, projection)
        if point is None:
            continue
        x, y = screen(*point)
        distance=math.hypot(x-event_x,y-event_y)
        if distance<=radius:hits.append((distance,p))
    return min(hits,key=lambda h:h[0])[1] if hits else None
