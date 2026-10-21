"""Verified 1262 ItemData_C NPC shop prices and sell restrictions.

Source: official binary ItemData:New layout, not TextData_C or TalkData_C.
All prices are baseline data, NOT server-authoritative transaction totals.
"""
import gzip
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from wlre.paths import RESOURCE_ROOT

FILENAME = 'npc_item_data_1262.json.gz'
SOURCE_SHA256 = '5fea03839a3e737ff33c5462fc553ab88966de5b02d1c95d71d3ffb54351ece1'
CATALOG_SHA256 = '94f45d1b0e4f8c8587219b5c87c3a7e5f65b5573487a1e8d4d7f64f35e2ceb17'
CATALOG_BYTES = 112854
RECORD_COUNT = 11287
MAX_UNCOMPRESSED = 4 * 1024 * 1024


def load_items(path=None):
    """Fail closed if the official 1262 source or record schema differs."""
    target = Path(path) if path is not None else RESOURCE_ROOT / FILENAME
    data = target.read_bytes()
    if path is None and (len(data) != CATALOG_BYTES
                         or hashlib.sha256(data).hexdigest() != CATALOG_SHA256):
        raise ValueError('官方 ItemData_C 索引檔大小／SHA-256 不符')
    if len(data) > 512 * 1024:
        raise ValueError('ItemData_C 索引檔過大')
    with gzip.open(target, 'rb') as stream:
        raw = stream.read(MAX_UNCOMPRESSED + 1)
    if len(raw) > MAX_UNCOMPRESSED:
        raise ValueError('ItemData_C 解壓縮後過大')
    document = json.loads(raw.decode('utf-8'))
    if (not isinstance(document, dict) or document.get('version') != 1262
            or document.get('source') != 'ItemData_C'
            or document.get('source_sha256') != SOURCE_SHA256
            or document.get('record_count') != RECORD_COUNT
            or not isinstance(document.get('records'), dict)
            or len(document['records']) != RECORD_COUNT):
        raise ValueError('官方 ItemData_C 來源／版本／筆數驗證失敗')
    result = {}
    expected = {'name', 'price', 'sell_price', 'restrict', 'open_used', 'need_level'}
    for key, record in document['records'].items():
        if (not isinstance(key, str) or not key.isdecimal()
                or str(int(key)) != key or not 1 <= int(key) <= 65535
                or not isinstance(record, dict) or set(record) != expected
                or not isinstance(record['name'], str)
                or not 0 < len(record['name']) <= 512
                or any(type(record[field]) is not int
                       for field in ('price', 'sell_price', 'restrict',
                                     'open_used', 'need_level'))
                or not all(0 <= record[field] <= 0xffffffff
                           for field in ('price', 'sell_price'))
                or not 0 <= record['restrict'] <= 65535
                or not 0 <= record['open_used'] <= 255
                or not 0 <= record['need_level'] <= 255):
            raise ValueError('ItemData_C 有無效的物品 ID 或交易欄位')
        result[int(key)] = record
    return result


@lru_cache(maxsize=1)
def item_catalog():
    """Memoize the immutable built-in, fully checksum-verified catalogue."""
    return load_items()


def sellable(item):
    """Official ItemData:CanSale, restrict bit 5 => 0x0010 no NPC selling."""
    return bool(isinstance(item, dict) and
                type(item.get('restrict')) is int and
                item['restrict'] & 16 == 0)
