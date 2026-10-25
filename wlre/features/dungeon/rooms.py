"""Normal dungeon headcount uses the verified StageData minimum, not capacity.

Pure UI display helper; command eligibility still belongs to network services.
"""
from wlre.services.instance_browser import entries_for


def dungeon_headcount_status(room, members, count, local_role_id=None, *,
                             can_begin=False):
    stage = next((row for row in entries_for('main')
                  if row['kind'] == 1 and row['map_id'] == room.get('room_id')),
                 None)
    if stage is None:
        return '一般副本：尚未確認此房間所屬的官方副本，無法判定最低人數'
    minimum, maximum = stage['min_members'], stage['max_members']
    prefix = '一般副本：目前 %d/%d 人' % (count, minimum)
    expected = room.get('members')
    if (type(expected) is not int or count != expected
            or not isinstance(members, (list, tuple))
            or not any(member.get('role_id') == local_role_id for member in members)):
        return prefix + '；伺服器成員名單尚未完整同步'
    if count < minimum:
        return prefix + '，尚缺 %d 人（上限 %d 人）' % (minimum - count, maximum)
    if count > maximum:
        return prefix + '；超出官方人數上限，請等待成員重新同步'
    if can_begin:
        return prefix + '，已達最低人數（上限 %d 人）；房主可以開始挑戰' % maximum
    return prefix + '，已達最低人數（上限 %d 人）；等待房主或其他開始條件確認' % maximum

