"""Offline ItemData_C v1 parser for read-only NPC shop base prices.

Layout derived from provided Lua/Data/ItemData.lua; unknown changes fail closed.
No real server discounts, offers, currency balance or transaction permissions.
"""
from __future__ import annotations

import hashlib

from wlre.services.parser_diagnostics import diagnosed, checkpoint, read_checkpoint

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
        read_checkpoint(self.pos, n, len(self.data) - self.pos)
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
            checkpoint(actual=size, expected_max=MAX_TEXT,
                       constraint='even_utf16_length' if allow_empty else 'nonempty_even_utf16_length')
            raise ItemDataDecodeError('Invalid ItemData Unicode byte length')
        try:
            text=self.take(size).decode('utf-16-le','strict').rstrip('\x00')
        except UnicodeDecodeError as exc:
            raise ItemDataDecodeError('Invalid ItemData Unicode data') from exc
        if not text and not allow_empty:
            raise ItemDataDecodeError('Empty ItemData name')
        return text


@diagnosed('itemdata-v1')
def parse_itemdata(raw: bytes, *, package_version=None, include_skill_link=False) -> dict[int,dict]:
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
    if include_skill_link and not is_1296:
        raise ItemDataDecodeError('Skill link needs reviewed ItemData source')
    r=Reader(raw)
    count=r.u32()
    if not 0 < count <= MAX_ITEMS:
        raise ItemDataDecodeError('ItemData record count outside reviewed range')
    result={}
    for index in range(count):
        checkpoint(offset=r.pos, field='name_length', record=index + 1)
        name=r.utf16()
        kind=r.u8()
        checkpoint(offset=r.pos, field='kind_name_length')
        r.utf16(allow_empty=True)   # kindName
        checkpoint(offset=r.pos, field='item_id')
        iid=r.u16()
        if not 1<=iid<=65535 or iid in result:
            raise ItemDataDecodeError('Invalid or duplicate ItemData item ID')
        order,icon_id,shop_icon_id=r.u16(),r.u16(),r.u16()
        r.skip(4*2)
        attributes=[dict(kind=r.u16(),effect=r.u8(),value=int.from_bytes(r.take(4),'little',signed=True)) for _ in range(2)]
        material,level,fit_type,special=r.u8(),r.u8(),r.u8(),r.u8()
        r.skip(4*4*4)
        open_used=r.u8()
        need_level=r.u8()
        price=r.u32()
        sell_price=r.u32()
        r.skip(1)
        restrict=r.u16()
        r.skip(4 + 1 + 4)
        skill_link=r.u16()
        spares=[r.u16() for _ in range(5)]
        checkpoint(offset=r.pos, field='description_length')
        desc_size=r.u16()
        if desc_size>MAX_TEXT or desc_size%2:
            raise ItemDataDecodeError('Invalid ItemData description length')
        r.skip(desc_size)
        size_l,size_w,size_h=r.u8(),r.u8(),r.u8()
        r.skip(2)
        item_w,item_h=r.u8(),r.u8()
        r.skip(1+2+2+2+2+1+1+1)
        r.skip(1+1+1)
        available_time,limited_time,use_count=r.u16(),r.u16(),r.u16()
        r.skip(2+2)
        r.skip(6*4)
        r.skip(2+2+1)
        flags2=r.u8()
        r.skip(1+1+1+1+2+1)
        r.skip(5*2)
        r.skip(1+2+2+2)
        result[iid]={'name':name,'price':price,'sell_price':sell_price,
                     'restrict':restrict,'open_used':open_used,
                     'need_level':need_level}
        if is_1296:
            checkpoint(offset=r.pos, field='unknown_tail_1296')
            tail=r.take(2)
            result[iid]['unknown_tail_1296_hex'] = tail.hex()  # Preserve diagnostic compatibility.
            # Only expose these additional semantics for the independently
            # pinned 1296 source and its decoded official ItemData.lua.
            result[iid].update(kind=kind,order=order,icon_id=icon_id,
                attributes=attributes,flags2=flags2,is_pvp_time_over=bool(flags2&1),
                shop_icon_id=shop_icon_id,material=material,level=level,
                fit_type=fit_type,special=special,spares=spares,
                size_l=size_l,size_w=size_w,size_h=size_h,item_w=item_w,item_h=item_h,
                available_time=available_time,limited_time=limited_time,use_count=use_count,
                style_bank_set_sort_id=int.from_bytes(tail,'little'))
            from wlre.services.world.item_stack_rules import can_overlap
            result[iid]['stackable']=can_overlap(iid,result[iid])
            if include_skill_link:result[iid]['skill_link']=skill_link
    checkpoint(offset=r.pos, field='end_of_file', expected=len(raw), actual=r.pos)
    if r.pos!=len(raw):
        raise ItemDataDecodeError('ItemData record layout changed or trailing bytes')
    return result
