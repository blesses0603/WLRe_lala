"""Display packet evidence without treating destinations as arrival acknowledgements."""
from wlre.services.world.map_names import map_label


def point_text(point):
    scene=point.get('scene')
    name=map_label(scene) if scene is not None else '地圖未知'
    return f"{name} X={point['x']} Y={point['y']}"


def movement_summary(check):
    if not check:return ''
    target=point_text(check['target'])
    role=check.get('role_id')
    label='目的地' if check['target'].get('source')=='local_goal' else '移動座標'
    prefix=f"角色 ID={role if role is not None else '未知'}｜{label} {target}"
    status=check['status']
    if status=='waiting':return prefix+'｜等待位置更新'
    fix=check['confirmation']
    result={'matched':'位置已更新',
            'different_position':'位置與目的地不同',
            'scene_changed':'地圖已切換'}[status]
    return prefix+f"｜{result}｜{point_text(fix)}"


