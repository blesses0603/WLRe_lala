"""Decode official 1262 TalkData_C text records without executing Lua.

The on-disk dialogue catalogue is optional: no fabricated NPC dialogue when
the extracted game TextAsset is unavailable. A supplied file's SHA256 proves
integrity of that file, not that its source is official.
"""
import gzip
import hashlib
import json
import re
import struct
from pathlib import Path

from wlre.paths import RESOURCE_ROOT

MAX_BINARY_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 65536
SOURCE = 'TalkData_C'
VERSION = 1262
CATALOG_NAME = 'npc_talk_1262.json.gz'
_HASH = re.compile(r'^[0-9a-f]{64}$')


def parse_talk_data(raw):
    """Parse TalkData.OnLoadTalkData / TalkData.New, strictly including EOF.

    i32 count; for each row: u16 id, u16 UTF-16LE byte length, text bytes,
    five reserved u8, u16 voice ID, four reserved u16, five reserved i32.
    """
    if not isinstance(raw, bytes) or len(raw) < 4 or len(raw) > MAX_BINARY_BYTES:
        raise ValueError('TalkData_C 大小不合法')
    count = struct.unpack_from('<i', raw, 0)[0]
    if count < 1 or count > MAX_ENTRIES or count > (len(raw) - 4) // 39:
        raise ValueError('TalkData_C 筆數超出資料邊界')
    pos, rows = 4, {}
    for _ in range(count):
        if len(raw) - pos < 39:
            raise ValueError('TalkData_C 資料遭到截斷')
        ident, size = struct.unpack_from('<HH', raw, pos)
        pos += 4
        if size % 2 or size > 32768 or len(raw) - pos < size + 35:
            raise ValueError('TalkData_C 字串長度不合法')
        try:
            value = raw[pos:pos + size].decode('utf-16le', errors='strict').rstrip('\x00')
        except UnicodeDecodeError as exc:
            raise ValueError('TalkData_C 文字不是合法 UTF-16LE') from exc
        pos += size
        pos += 5  # reserved bytes
        voice = struct.unpack_from('<H', raw, pos)[0]
        pos += 2 + 4 * 2 + 5 * 4
        if ident in rows:
            raise ValueError('TalkData_C 對話 ID 重複')
        if any(ord(c) < 32 and c not in '\r\n\t' for c in value):
            raise ValueError('TalkData_C 含無效控制字元')
        rows[ident] = {'text': value, 'voice_id': voice}
    if pos != len(raw):
        raise ValueError('TalkData_C 存在未知尾端資料')
    return rows


def make_catalog(raw):
    return {'version': VERSION, 'source': SOURCE,
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'records': {str(k): v for k, v in parse_talk_data(raw).items()}}


def load_catalog(path=None):
    """Optional bounded read. Never treat arbitrary JSON as official proof."""
    path = Path(path) if path is not None else RESOURCE_ROOT / CATALOG_NAME
    if not path.is_file():
        return {}
    with gzip.open(path, 'rb') as stream:
        contents = stream.read(MAX_BINARY_BYTES + 1)
    if len(contents) > MAX_BINARY_BYTES:
        raise ValueError('NPC 對話索引解壓縮超過安全上限')
    data = json.loads(contents.decode('utf-8'))
    if (not isinstance(data, dict) or data.get('version') != VERSION
            or data.get('source') != SOURCE
            or not isinstance(data.get('source_sha256'), str)
            or not _HASH.fullmatch(data['source_sha256'])
            or not isinstance(data.get('records'), dict)
            or len(data['records']) > MAX_ENTRIES):
        raise ValueError('NPC 對話索引版本或來源欄位錯誤')
    if path == RESOURCE_ROOT / CATALOG_NAME:
        from wlre.services.world.npc_asset_install import ASSETS
        _,_,_,source_digest,expected_count=ASSETS[CATALOG_NAME]
        if (data['source_sha256']!=source_digest or len(data['records'])!=expected_count):
            raise ValueError('官方 NPC 文字索引的來源／筆數不符')
    normalized = {}
    for key, row in data['records'].items():
        if (not isinstance(key, str) or not key.isdecimal() or
                not 0 <= int(key) <= 65535 or str(int(key)) != key or
                not isinstance(row, dict) or not isinstance(row.get('text'), str)
                or len(row['text']) > 16384 or
                any(ord(c) < 32 and c not in '\r\n\t' for c in row['text'])
                or type(row.get('voice_id')) is not int or
                not 0 <= row['voice_id'] <= 65535):
            raise ValueError('NPC 對話索引包含無效資料')
        normalized[int(key)] = row['text']
    return normalized


def dialogue_text(catalog, text_id):
    """Return only a verified numeric lookup; unknown ID means no known text."""
    return catalog.get(text_id) if type(text_id) is int else None
