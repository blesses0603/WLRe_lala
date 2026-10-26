"""1262 DungeonData / CooperateEventData / StageData binary table readers.

Derived from Lua/Data/{DungeonData,CooperateEventData,StageData,AwardData}.lua.
Records are NOT fabricated when the corresponding official binary is absent.
"""
import json
from pathlib import Path

from wlre.network.wire import Reader, ProtocolError

MAX_RECORDS = 20000
REWARD_SLOTS = 16


def _count(reader):
    count = reader.i32()
    if count < 0 or count > MAX_RECORDS:
        raise ProtocolError('副本資料筆數超出安全範圍')
    return count


def _award(reader):
    return {'kind': reader.u8(), 'id': reader.u32(), 'value': reader.u32()}


def _flags(reader):
    values = []
    for part in range(2):
        bits = reader.u8()
        values.extend(part * 8 + offset + 1 for offset in range(8) if bits & (1 << offset))
    return values


def parse_dungeons(data):
    """Read DungeonData_C, including exactly 16 AwardData entries per row."""
    r = Reader(data)
    result = []
    for _ in range(_count(r)):
        row = {'id': r.u16(), 'kind': r.u8(), 'para_kind': r.u8(),
               'map_id': r.u16(), 'description_id': r.u32(),
               'picture': r.u8(), 'score_display': r.u8(),
               'award_group': r.u8(), 'npc_x': r.u16(),
               'npc_y': r.u16(), 'npc_id': r.u16(), 'quick_id': r.u8()}
        row['awards'] = [_award(r) for _ in range(REWARD_SLOTS)]
        row['double_award_slots'] = _flags(r)
        row['special_award_slots'] = _flags(r)
        if row['kind'] not in (1, 2, 3):
            raise ProtocolError('未知副本種類；拒絕套用不相符資料')
        result.append(row)
    r.end()
    return result


def parse_cooperative_events(data):
    """Read CooperateEventData_C; 4 named follower slots + one AwardData."""
    r = Reader(data)
    result = []
    for _ in range(_count(r)):
        row = {'id': r.u8(), 'text_id': r.u32(), 'npc_x': r.u16(),
               'npc_y': r.u16(), 'fight_count': r.u8(),
               'step_mark_id': r.u16(), 'finish_mark_id': r.u16(),
               'sell_data_id': r.u16(),
               'follower_ids': [r.u16() for _ in range(4)],
               'follower_reward': _award(r)}
        result.append(row)
    r.end()
    return result


def parse_stages(data):
    """Read ScenesData_C records via StageData:New (Lua/Logic/Data.lua)."""
    r = Reader(data)
    result = {}
    for _ in range(_count(r)):
        stage_id = r.u16()
        r.take(2)  # landType / businessType
        name_id = r.u32()
        model_id = r.u16()
        r.u16()  # musicName
        r.take(3)  # limitType / isOpen / specialType
        r.take(2)  # sceneLightId
        r.take(4)  # englishName
        max_members, tag, min_members, room_count, group = (r.u8() for _ in range(5))
        flag = r.u16()
        min_level = r.u16()
        time_limit = r.u16()
        r.take(20)  # five reserved UInt32
        map_width, map_height = r.u16(), r.u16()
        r.u8()  # camera angle
        pos_x_ratio, pos_y_ratio = r.u8(), r.u8()
        small_offset_x, small_offset_y = r.u16(), r.u16()
        r.take(8)  # camera start/end X/Y
        r.take(5)  # water / activity / hide-player / no-battle / second-job
        if stage_id in result:
            raise ProtocolError('重複 StageData ID')
        result[stage_id] = {
            'id': stage_id, 'name_id': name_id, 'model_id': model_id,
            'max_members': max_members,
            'min_members': min_members, 'min_level': min_level,
            'time_minutes': time_limit, 'tag': tag,
            'room_capacity': room_count, 'group': group, 'flag': flag,
            # Official 1275 StageData ratios for EveDoorLinks grid XY.
            # Only use these for separately checked portal map markers.
            'pos_x_ratio': pos_x_ratio, 'pos_y_ratio': pos_y_ratio,
            'map_width': map_width, 'map_height': map_height,
            'small_offset_x': small_offset_x, 'small_offset_y': small_offset_y,
        }
    r.end()
    return result


def catalog(dungeon_data, cooperative_data, stage_data, names=None):
    """Generate an evidence-labeled catalog from verified binary inputs.

    Text IDs are kept when localization is missing; no invented dungeon names.
    """
    rows = parse_dungeons(dungeon_data)
    events = {e['id']: e for e in parse_cooperative_events(cooperative_data)}
    stages = parse_stages(stage_data)
    names = names or {}
    entries = []
    for dungeon in rows:
        stage = stages.get(dungeon['map_id'])
        entry = dict(dungeon)
        entry['stage'] = stage
        entry['name'] = names.get(stage['name_id']) if stage else None
        if dungeon['kind'] == 2:
            entry['cooperative_event'] = events.get(dungeon['npc_id'])
        entries.append(entry)
    return {'version': 1262, 'verified_binary_layout': True,
            'source': 'DungeonData_C / CooperateEventData_C / ScenesData_C',
            'records': entries, 'cooperative_events': list(events.values())}


def save_catalog(path, dungeon_data, cooperative_data, stage_data, names=None):
    """Offline export only, not an automatic network or game-file reader."""
    result = catalog(dungeon_data, cooperative_data, stage_data, names)
    Path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    return result
