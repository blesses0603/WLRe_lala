"""Strict read-only Eve v115 NewNpc / NewInteract index derivation.

Field layout follows the provided 1262 Lua/Data/EventData.lua and
Lua/Logic/Data.lua, as well as the existing 1275 Eve NewDoor reader.
Unknown revisions fail closed; no event execution or packet authorization.
"""
from __future__ import annotations

import json
import struct

MAX_SCENES = 4096
MAX_RECORDS = 20000
MAX_ROWS_PER_TYPE = 4096
NAME_BYTES = 20
PARA_NODES = 11


class EveDecodeError(ValueError):
    """Unreviewed or truncated Eve v115 scene/event data."""


class Reader:
    def __init__(self, raw, start, end):
        self.raw, self.pos, self.end = raw, start, end

    def take(self, n):
        if n < 0 or self.pos + n > self.end:
            raise EveDecodeError('Eve record exceeds verified scene limits')
        value = self.raw[self.pos:self.pos+n]
        self.pos += n
        return value

    def skip(self, n):
        self.take(n)

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return int.from_bytes(self.take(2), 'little')

    def u32(self):
        return int.from_bytes(self.take(4), 'little')


def _common(r):
    r.skip(NAME_BYTES + 1)
    x, y = r.u32(), r.u32()
    events = r.take(r.u8())
    r.skip(r.u8())  # lead event IDs
    r.skip(1)        # sign icon
    return x, y, list(events)


def _npc(r):
    index = r.u16()
    x, y, events = _common(r)
    npc_id = r.u32()
    r.skip(3)  # direction / move mode / return mode
    r.skip(r.u8() * 12)
    r.skip(1 + 1 + 4 + 4 + 2 + 1)
    r.skip(r.u8() * (4 + PARA_NODES * 8 + PARA_NODES))
    r.skip(2 + 2 + 4 + 1 + 4 + 2 + 2 + 1 + 5 * 4)
    if npc_id == 0:
        raise EveDecodeError('NPC source ID is invalid')
    return {'index': index, 'npc_id': npc_id, 'x': x, 'y': y,
            'event_count': len(events), 'event_ids': events}


def _interact(r):
    index = r.u16()
    r.skip(NAME_BYTES)
    form_kind = r.u8()
    link_number = r.u16()
    count = r.u8()
    if form_kind not in (1, 2, 3):
        raise EveDecodeError('Unknown interaction form kind')
    items = []
    for _ in range(count):
        item_id = r.u8()
        text_id = r.u16()
        database_kind = r.u8()
        kind = r.u8()
        items.append({'id': item_id, 'text_id': text_id,
                      'database_kind': database_kind, 'kind': kind})
    return {'index': index, 'form_kind': form_kind,
            'link_number': link_number, 'items': items}


def _skip_event(r):
    r.skip(2 + 1 + NAME_BYTES)
    for _ in range(r.u8()):
        r.skip(22)
        r.skip(22 * r.u8())


def _skip_group(r):
    r.skip(2 + NAME_BYTES + 1 + 2 + 1 + 1)
    r.skip(3 * r.u16())


def _skip_battle(r):
    r.skip(2)
    _common(r)
    r.skip(1 + 2 + 1)
    r.skip(3 * r.u8())
    r.skip(3 * r.u8())
    r.skip(1)


def _scene(r, source):
    r.skip(2)  # map model ID
    if r.u16() != 115:
        raise EveDecodeError('Unsupported Eve scene format, expected 115')
    groups = (
        ('npc', _npc), ('door', None), ('mine', None),
        ('goods', None), ('event', _skip_event), ('group', _skip_group),
        ('convey', None), ('interact', _interact), ('battle', _skip_battle),
        ('lead_event', _skip_event), ('lead_group', _skip_group),
    )
    selected = 'npc' if source == 'EventData.NewNpc' else 'interact'
    result = []
    counts = []
    scene_start = r.pos - 4
    for kind, decode in groups:
        try:
            count = r.u16()
            if count > MAX_ROWS_PER_TYPE:
                raise EveDecodeError('Eve per-scene event count exceeds limit')
            counts.append((kind, count))
            seen = set()
            for record_index in range(count):
                try:
                    if kind in ('npc', 'interact'):
                        row = decode(r)
                    elif kind in ('event', 'lead_event', 'group', 'lead_group', 'battle'):
                        decode(r)
                        row = None
                    elif kind in ('door', 'mine', 'goods'):
                        r.skip(2)
                        _common(r)
                        r.skip({'door': 29, 'mine': 10, 'goods': 11}[kind])
                        row = None
                    else:  # convey
                        r.skip(2 + NAME_BYTES + 2 + 4 + 4 + 1 + 2)
                        row = None
                    if row is not None:
                        if row['index'] in seen:
                            raise EveDecodeError('Duplicate event index in scene')
                        seen.add(row['index'])
                        if kind == selected:
                            result.append(row)
                except EveDecodeError as exc:
                    raise EveDecodeError(
                        f'{kind} 第 {record_index + 1}/{count} 筆'
                        f'（場景內偏移 {r.pos - scene_start}）：{exc}') from exc
        except EveDecodeError as exc:
            if f'{kind} 第 ' in str(exc):
                raise
            raise EveDecodeError(
                f'{kind} 區段（場景內偏移 {r.pos - scene_start}）：{exc}') from exc
    if r.pos != r.end:
        remaining = r.end - r.pos
        # Expose only position, lengths and section counts, never raw bytes.
        # Zero padding might explain the difference but is NOT silently trusted.
        is_zero = (remaining > 0 and
                   not any(r.raw[r.pos:r.end]))
        sizes = ','.join(f'{kind}:{count}' for kind, count in counts)
        raise EveDecodeError(
            'Scene size does not match audited Eve v115 layout'
            f'（已讀 {r.pos-scene_start}，'
            f'剩餘 {remaining} bytes，尾段全零={is_zero}，'
            f'事件數={sizes}）')
    return result


def derive_eve_index(raw: bytes, source: str) -> bytes:
    """Produce the schema-v1 UTF-8 JSON accepted by the NPC/shop adapters."""
    if type(raw) is not bytes or not 12 <= len(raw) <= 16 * 1024 * 1024:
        raise EveDecodeError('Missing or oversized Eve source')
    if source not in ('EventData.NewNpc', 'EventData.NewInteract'):
        raise EveDecodeError('Unknown requested Eve index')
    count = struct.unpack_from('<I', raw, 8)[0]
    if not 0 < count <= MAX_SCENES or 12 + 12 * count > len(raw):
        raise EveDecodeError('Eve header/scene count invalid')
    scenes = {}
    segments = []
    records = 0
    for idx in range(count):
        scene_id, model, offset, size = struct.unpack_from('<HHII', raw, 12 + 12 * idx)
        if (scene_id in scenes or offset < 12 + 12 * count or size < 6
                or offset + size > len(raw)):
            raise EveDecodeError('Duplicate scene ID or out-of-bounds offset')
        scenes[str(scene_id)] = None
        segments.append((offset, offset + size, str(scene_id)))
    segments.sort()
    for i, (start, end, scene) in enumerate(segments):
        if i and segments[i-1][1] > start:
            raise EveDecodeError('Eve scene segments overlap')
        try:
            row = _scene(Reader(raw, start, end), source)
        except EveDecodeError as exc:
            # Report only numeric scene ID and bounded binary offset.
            # Never expose game payloads or arbitrary filesystem paths.
            raise EveDecodeError(
                f'場景 {scene}（偏移 {start}，長度 {end-start}）：{exc}') from exc
        records += len(row)
        if records > MAX_RECORDS:
            raise EveDecodeError('Eve selected index exceeds record limit')
        scenes[scene] = row
    # Stable deterministic serialization, independent from source ordering.
    document = {'schema_version': 1, 'source': source,
                'record_count': records,
                'scenes': dict(sorted(scenes.items(), key=lambda kv: int(kv[0])))}
    return json.dumps(document, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
