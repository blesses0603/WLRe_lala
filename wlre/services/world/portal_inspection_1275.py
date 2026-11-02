"""P3: verified-version read-only portal inspection fields.

A source grid coordinate, packet-space XY and arrival XY are different
concepts. These fields are for diagnostics/UI only, not a new trigger index
or permission to send C20-8.
"""

from wlre.services.world.catalog_source_policy import is_official_revision
from wlre.services.world.scene_names_1275 import source_scene_label


def link_inspection_fields(reference, scene, index, scene_names):
    """Describe an authenticated EveDoorLinks row without granting travel."""
    base = {
        'reference_destination_scene_id': None,
        'reference_destination_label': None,
        'reference_source_grid': None,
        'reference_arrival_grid': None,
        'reference_arrival_xy': None,
        'reference_source_xy': None,
        'reference_destination_defined': False,
        'reference_issues': (),
    }
    if (not isinstance(reference, dict)
            or reference.get('source_kind') != '1275_eve_door_links_reference'
            or reference.get('scene') != scene
            or reference.get('index') != index
            or type(scene) is not int or type(index) is not int):
        return base
    target = reference.get('destination')
    if type(target) is int and 0 < target <= 65535:
        known = reference.get('destination_defined') is True
        base['reference_destination_scene_id'] = target
        base['reference_destination_defined'] = known
        base['reference_destination_label'] = (
            source_scene_label(target, scene_names) if known
            else f'場景 {target}（1275 場景表未定義）')
    for field, xname, yname, flag in (
        ('reference_source_grid', 'source_grid_x', 'source_grid_y', None),
        ('reference_arrival_grid', 'arrival_grid_x', 'arrival_grid_y', None),
        ('reference_source_xy', 'x', 'y', 'position_verified'),
        ('reference_arrival_xy', 'arrival_x', 'arrival_y', 'arrival_verified'),
    ):
        if flag and reference.get(flag) is not True:
            continue
        x, y = reference.get(xname), reference.get(yname)
        if (type(x) is int and type(y) is int
                and 0 <= x <= 65535 and 0 <= y <= 65535):
            base[field] = (x, y)
    issues = reference.get('issues', ())
    if isinstance(issues, (list, tuple)):
        base['reference_issues'] = tuple(
            item for item in issues
            if type(item) is str and len(item) <= 80)[:16]
    return base


def portal_inspection_text(portal):
    """Human-readable 1275 source/arrival status, explicitly non-authorizing."""
    if not isinstance(portal, dict) or not is_official_revision(portal.get('source_revision')):
        return ''
    target = portal.get('reference_destination_label')
    if (not target and portal.get('destination_verified') is True
            and portal.get('binding_kind') == 'unique_boundary_touch_region'):
        target = portal.get('destination_label')
    if target is None and type(portal.get('hidden_destination_scene_id')) is int:
        hidden = portal['hidden_destination_scene_id']
        target = portal.get('display_destination_label') or (
            f'場景 {hidden}（官方隱藏傳點參考）')
    if not target:
        return '官方傳點目的地尚無可辨識的連線資料；不可直接傳送'
    source = portal.get('reference_source_xy')
    source_grid = portal.get('reference_source_grid')
    arrival = portal.get('reference_arrival_xy')
    arrival_grid = portal.get('reference_arrival_grid')
    parts = ['官方唯讀連線：' + target]
    if portal.get('destination_verified') is True:
        parts[0] = '已配對目的地：' + str(portal.get('destination_label') or target)
    marker_name = portal.get('official_name')
    door_name = portal.get('door_event_name')
    if marker_name:parts.append('原地圖標籤：' + marker_name)
    if door_name:parts.append('門容器原名：' + door_name)
    index, link_index = portal.get('direct_door_index'), portal.get('link_index')
    if type(index) is int:parts.append(f'實際門編號 {index}')
    if type(link_index) is int:parts.append(f'連線序號 {link_index}')
    events = portal.get('touch_event_ids')
    if events:parts.append('觸碰事件 ' + ', '.join(str(i) for i in events))
    if portal.get('touch_event_records'):
        parts.append('事件條件與效果明細已保留；換圖效果語意尚未獨立核對')
    if source is not None:
        parts.append(f'來源座標 {source}')
    elif source_grid is not None:
        parts.append(f'來源原始格點 {source_grid}（倍率待核對）')
    if arrival is not None:
        parts.append(f'落點座標 {arrival}')
    elif arrival_grid is not None:
        parts.append(f'落點原始格點 {arrival_grid}（倍率待核對）')
    if portal.get('destination_verified') is not True:
        reason_labels = {
            'missing_eve_door': '缺少門事件',
            'duplicate_eve_door': '門事件索引重複',
            'missing_normal_stage_marker': '缺少普通傳點標記',
            'source_scene_undefined': '來源場景無正式定義',
            'destination_scene_undefined': '目的場景無正式定義',
            'source_coordinate_uncalibrated': '來源座標倍率未確認',
            'arrival_coordinate_uncalibrated': '抵達座標倍率未確認',
        }
        issues = portal.get('reference_issues', ())
        if isinstance(issues, (tuple, list)):
            labels = list(dict.fromkeys(
                reason_labels[x] for x in issues if x in reason_labels))
            if labels:
                parts.append('待核對：' + '、'.join(labels[:4]))
        parts.append('僅供查看，未核准換圖')
    else:
        if portal.get('binding_kind') == 'unique_boundary_touch_region':
            parts.append('海岸碰撞範圍與實際觸碰門編號已核對')
        parts.append('門索引交叉核對完成，伺服器傳送尚待驗收')
    return '｜'.join(parts)
