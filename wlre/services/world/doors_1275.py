"""Strict, read-only EventData.NewDoor index from official 1275 Eve.bytes.

A verified door index is still NOT proof that an existing 1262 portal route,
destination, or C20-8 trigger is authorized on the live 1275 server.
"""
import hashlib
import struct

SOURCE_SHA256 = 'f5fc56b1d6cf7c00dd20b2f35c04b4cbc60c92ccdb6085fbe465c7e6526745ad'


class DoorSourceError(ValueError):
    pass


class _Reader:
    def __init__(self, raw, start, end):
        self.raw, self.pos, self.end = raw, start, end

    def take(self, length):
        if length < 0 or self.pos + length > self.end:
            raise DoorSourceError('Eve Door 解析超出範圍')
        at = self.pos
        self.pos += length
        return self.raw[at:self.pos]

    def skip(self, length):
        self.take(length)

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return int.from_bytes(self.take(2), 'little')

    def u32(self):
        return int.from_bytes(self.take(4), 'little')


def _event_name(reader):
    raw = reader.take(20).split(b'\0',1)[0]
    try:
        name = raw.decode('cp950').strip()
    except UnicodeDecodeError:
        return {'name': None, 'name_bytes': raw.hex(), 'name_valid': False}
    valid = bool(name) and not any(ord(ch)<32 for ch in name)
    return {'name': name if valid else None, 'name_bytes': raw.hex(), 'name_valid': valid}


def _common(reader):
    name = _event_name(reader)
    reader.u8()
    x, y = reader.u32(), reader.u32()
    event_count = reader.u8()
    events = list(reader.take(event_count))
    leader_count = reader.u8()
    reader.skip(leader_count)
    reader.u8()
    return {**name, 'x': x, 'y': y, 'event_ids': events}


def _npc(reader):
    reader.u16()
    _common(reader)
    reader.skip(4 + 1 + 1 + 1)
    node_count = reader.u8()
    reader.skip(node_count * 12)
    reader.skip(1 + 1 + 4 + 4 + 2 + 1)
    param_count = reader.u8()
    reader.skip(param_count * (4 + 11*8 + 11))
    reader.skip(2 + 2 + 4 + 1 + 4 + 2 + 2 + 1 + 5*4)


def _event_parameters(reader, *, signed):
    """EventData.NewEvent layout; preserve effects without guessing their meaning."""
    fields = ('id','para_main','para_kind','para_style','para_type','para_operator',
              'para_value','group_number','para_class1','para_class2')
    values = struct.unpack('<BBHHHB' + ('i' if signed else 'I') + 'BII',reader.take(22))
    return dict(zip(fields,values))


def _touch_events(reader, needed_event_ids):
    # EventData.NewMine/NewGoods precede NewEvent. Keep each variable common
    # record aligned; a door's event_ids alone do not prove PlayerTouch.
    for tail in (10, 11):
        count = reader.u16()
        if count > 4096:raise DoorSourceError('Eve 事件物件數量不合理')
        for _ in range(count):
            reader.u16();_common(reader);reader.skip(tail)
    count = reader.u16()
    if count > 4096:raise DoorSourceError('Eve 事件數量不合理')
    touch, seen = {}, set()
    for _ in range(count):
        index, occur = reader.u16(), reader.u8()
        if index in seen:raise DoorSourceError('Eve 場景內重複的事件 index')
        seen.add(index)
        name = _event_name(reader)
        conditions = []
        keep = bool(occur & 2) and index in needed_event_ids
        for _ in range(reader.u8()):
            if keep:
                condition = _event_parameters(reader, signed=False)
                results = [_event_parameters(reader, signed=True) for _ in range(reader.u8())]
                conditions.append({'data':condition, 'results':results})
            else:
                reader.skip(22)
                reader.skip(22 * reader.u8())
        if keep:  # Define.lua EEventOccurType.PlayerTouch
            touch[index] = {'index':index, 'occur_type':occur, **name,
                            'conditions':conditions, 'destination_decoded':False}
    return touch


def parse_doors_1275(raw):
    """Read 1262 scene headers and 1275 NewDoor entries with exact source pin."""
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise DoorSourceError('1275 Eve.bytes SHA-256 與已確認來源不符')
    return parse_verified_doors(raw, expected_scene_count=1262)


def parse_verified_doors(raw, *, expected_scene_count=None):
    """Decode v115 doors from an already verified Bundle; no network approval."""
    if type(raw) is not bytes or not 12 <= len(raw) <= 32 * 1024 * 1024:
        raise DoorSourceError('Eve 表頭或大小無效')
    if len(raw) < 12:
        raise DoorSourceError('1275 Eve 表頭截斷')
    scene_count = struct.unpack_from('<I', raw, 8)[0]
    if (not 1 <= scene_count <= 4096
            or (expected_scene_count is not None and scene_count != expected_scene_count)
            or 12 + scene_count*12 > len(raw)):
        raise DoorSourceError('1275 Eve 場景數量或標頭不符')
    scenes = {}
    for i in range(scene_count):
        scene, model, offset, size = struct.unpack_from('<HHII', raw, 12 + i*12)
        if (scene in scenes or offset < 12 + scene_count*12
                or size < 6 or offset + size > len(raw)):
            raise DoorSourceError('1275 場景長度或偏移無效')
        reader = _Reader(raw, offset, offset + size)
        if reader.u16() != model or reader.u16() != 115:
            raise DoorSourceError('1275 場景內模型 ID／版本不符')
        npc_count = reader.u16()
        if npc_count > 4096:
            raise DoorSourceError('1275 場景 NPC 數量不合理')
        for _ in range(npc_count):
            _npc(reader)
        door_count = reader.u16()
        if door_count > 4096:
            raise DoorSourceError('1275 場景門數量不合理')
        entries, seen = [], set()
        for _ in range(door_count):
            index = reader.u16()
            row = _common(reader)
            right, bottom, sign_type = reader.u32(), reader.u32(), reader.u8()
            sign_x, sign_y = reader.u32(), reader.u32()
            col_x, col_y, col_z = reader.u32(), reader.u32(), reader.u32()
            if index in seen:
                raise DoorSourceError('1275 場景內重複的門事件 index')
            seen.add(index)
            entries.append({'index': index, **row, 'right': right, 'bottom': bottom,
                            'sign_type': sign_type, 'sign_x': sign_x, 'sign_y': sign_y,
                            'col_x': col_x, 'col_y': col_y, 'col_z': col_z})
        touch = _touch_events(reader, {i for row in entries for i in row['event_ids']})
        for row in entries:
            row['touch_event_ids'] = [i for i in row['event_ids'] if i in touch]
            row['touch_event_records'] = [touch[i] for i in row['touch_event_ids']]
        scenes[scene] = entries
    return scenes
