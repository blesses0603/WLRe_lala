"""Offline ItemData_C v1 parser for read-only NPC shop base prices.

Layout derived from provided Lua/Data/ItemData.lua; unknown changes fail closed.
No real server discounts, offers, currency balance or transaction permissions.
"""
from __future__ import annotations

MAX_ITEMS = 20000
MAX_TEXT = 8192


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


def parse_itemdata(raw: bytes) -> dict[int,dict]:
    """Return only confirmed item fields, never calculate live purchase totals."""
    if type(raw) is not bytes or not 4 < len(raw) <= 16*1024*1024:
        raise ItemDataDecodeError('ItemData is missing or oversized')
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
    if r.pos!=len(raw):
        raise ItemDataDecodeError('ItemData record layout changed or trailing bytes')
    return result
