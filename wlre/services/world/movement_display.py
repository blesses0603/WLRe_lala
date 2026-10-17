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
    label='目的地' if check['target'].get('source')=='local_goal' else '回報/通知座標'
    prefix=f"角色 ID={role if role is not None else '未知'}｜{label} {target}"
    status=check['status']
    if status=='waiting':return prefix+'｜等待位置確認（尚無後續本機位置回覆）'
    fix=check['confirmation']
    result={'matched':'位置回覆符合目的地',
            'different_position':'位置回覆與目的地不同，尚未確認抵達',
            'scene_changed':'位置回覆位於不同地圖，此次移動未確認抵達'}[status]
    return prefix+f"｜{result}｜{fix['source']} {point_text(fix)}"


