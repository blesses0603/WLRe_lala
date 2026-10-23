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


def _common(reader):
    reader.skip(20)
    reader.u8()
    x, y = reader.u32(), reader.u32()
    event_count = reader.u8()
    events = list(reader.take(event_count))
    leader_count = reader.u8()
    reader.skip(leader_count)
    reader.u8()
    return {'x': x, 'y': y, 'event_ids': events}


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


def parse_doors_1275(raw):
    """Read 1262 scene headers and 1275 NewDoor entries with exact source pin."""
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise DoorSourceError('1275 Eve.bytes SHA-256 與已確認來源不符')
    if len(raw) < 12:
        raise DoorSourceError('1275 Eve 表頭截斷')
    scene_count = struct.unpack_from('<I', raw, 8)[0]
    if scene_count != 1262 or 12 + scene_count*12 > len(raw):
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
            reader.skip(4*2 + 1 + 4*2 + 4*3)
            if index in seen:
                raise DoorSourceError('1275 場景內重複的門事件 index')
            seen.add(index)
            entries.append({'index': index, **row})
        scenes[scene] = entries
    return scenes
