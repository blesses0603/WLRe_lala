"""Only server-confirmed normal dungeon objectives and settlement notices."""


def dungeon_details(data, local_role_id=None):
    parts = []
    obj = data.get('objectives') or {}
    targets = obj.get('targets') or {}
    if targets:
        parts.append('擊殺目標：' + '、'.join(
            '#%s NPC%s %s/%s' % (idx, row.get('npc_id', '?'),
                                 row.get('kills', 0), row.get('required', '?'))
            for idx, row in sorted(targets.items())))
    boss = obj.get('boss') or {}
    if boss:
        parts.append('Boss NPC%s：%s' % (
            boss.get('npc_id', '?'), '已擊敗' if boss.get('defeated') else '未擊敗'))
    score = (obj.get('scores') or {}).get(str(local_role_id))
    if score:
        parts.append('個人積分：小怪 %s／Boss %s' %
                     (score.get('normal', 0), score.get('boss', 0)))
    if obj.get('records'):
        parts.append('新式副本結算紀錄：%s 人（依 S85-21-100）' %
                     len(obj['records']))
    if data.get('completed'):
        parts.append('副本完成：伺服器已確認')

    return '；'.join(parts)
