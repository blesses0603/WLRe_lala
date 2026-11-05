"""Offline ItemData_C v1 parser for read-only NPC shop base prices.

Layout derived from provided Lua/Data/ItemData.lua; unknown changes fail closed.
No real server discounts, offers, currency balance or transaction permissions.
"""
from __future__ import annotations

import hashlib

MAX_ITEMS = 20000
MAX_TEXT = 8192
ITEMDATA_1296_SHA256 = '5195d5ee8ae201dea55439274914930551176c3fcf50d735e03b09c5d04acbb4'


class ItemDataDecodeError(ValueError):
    pass


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, n):
        if n < 0 or self.pos+n > len(self.data):
            raise ItemDataDecodeError('ItemData record truncated')
        chunk = self.data[self.pos:self.pos+n]
        self.pos += n
        return chunk

    def skip(self,n):self.take(n)
    def u8(self):return self.take(1)[0]
    def u16(self):return int.from_bytes(self.take(2),'little')
    def u32(self):return int.from_bytes(self.take(4),'little')

    def utf16(self, *, allow_empty=False):
        size=self.u16()
        if (not allow_empty and not size) or size>MAX_TEXT or size%2:
            raise ItemDataDecodeError('Invalid ItemData Unicode byte length')
        try:
            text=self.take(size).decode('utf-16-le','strict').rstrip('\x00')
        except UnicodeDecodeError as exc:
            raise ItemDataDecodeError('Invalid ItemData Unicode data') from exc
        if not text and not allow_empty:
            raise ItemDataDecodeError('Empty ItemData name')
        return text


def parse_itemdata(raw: bytes, *, package_version=None) -> dict[int,dict]:
    """Return only confirmed item fields, never calculate live purchase totals."""
    if type(raw) is not bytes or not 4 < len(raw) <= 16*1024*1024:
        raise ItemDataDecodeError('ItemData is missing or oversized')
    version_1296 = '1296_2026_11_04_13_34_19_13'
    legacy_versions = {
        '1262_2026_10_14_15_00_34_84',
        '1275_2026_10_21_18_27_33_84',
        '1286_2026_10_29_13_42_37_94',
    }
    if package_version is not None and package_version not in legacy_versions | {version_1296}:
        raise ItemDataDecodeError('Unreviewed ItemData package version')
    is_1296 = hashlib.sha256(raw).hexdigest() == ITEMDATA_1296_SHA256
    if package_version == version_1296 and not is_1296:
        raise ItemDataDecodeError('ItemData 1296 source digest mismatch')
    if package_version in legacy_versions and is_1296:
        raise ItemDataDecodeError('ItemData source and package version differ')
    r=Reader(raw)
    count=r.u32()
    if not 0 < count <= MAX_ITEMS:
        raise ItemDataDecodeError('ItemData record count outside reviewed range')
    result={}
    for _ in range(count):
        name=r.utf16()
        r.skip(1)
        r.utf16(allow_empty=True)   # kindName
        iid=r.u16()
        if not 1<=iid<=65535 or iid in result:
            raise ItemDataDecodeError('Invalid or duplicate ItemData item ID')
        r.skip(2+2+2 + 4*2 + 2*(2+1+4) + 4 + 4*4*4)
        open_used=r.u8()
        need_level=r.u8()
        price=r.u32()
        sell_price=r.u32()
        r.skip(1)
        restrict=r.u16()
        r.skip(4 + 1 + 4 + 2 + 5*2)
        desc_size=r.u16()
        if desc_size>MAX_TEXT or desc_size%2:
            raise ItemDataDecodeError('Invalid ItemData description length')
        r.skip(desc_size)
        r.skip(3 + 2 + 1 + 1)
        r.skip(1+2+2+2+2+1+1+1)
        r.skip(1+1+1+2+2+2+2+2)
        r.skip(6*4)
        r.skip(2+2+1+1+1+1+1+1+2+1)
        r.skip(5*2)
        r.skip(1+2+2+2)
        result[iid]={'name':name,'price':price,'sell_price':sell_price,
                     'restrict':restrict,'open_used':open_used,
                     'need_level':need_level}
        if is_1296:
            result[iid]['unknown_tail_1296_hex'] = r.take(2).hex()
    if r.pos!=len(raw):
        raise ItemDataDecodeError('ItemData record layout changed or trailing bytes')
    return result
