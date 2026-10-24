"""Full 1275 ItemData_C reader based on Lua/Data/ItemData.lua::ItemData.New.

Only call with raw bytes from the already SHA-pinned 1275 DataCatalog.
No automatic network requests, no gameplay commands and no 1262 item fallback.
"""
from __future__ import annotations
import struct


class ItemData1275Error(ValueError):
    """1275 ItemData is invalid, incomplete or has an unsupported layout."""


class _Reader:
    def __init__(self, raw):
        if type(raw) is not bytes:
            raise ItemData1275Error('1275 ItemData_C 必須是二進位資料')
        self.raw, self.pos = raw, 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.raw):
            raise ItemData1275Error('1275 ItemData_C 資料已截斷')
        result = self.raw[self.pos:self.pos + n]
        self.pos += n
        return result

    def number(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize(fmt)))[0]

    def u8(self): return self.number('B')
    def u16(self): return self.number('H')
    def u32(self): return self.number('I')
    def i32(self): return self.number('i')

    def unicode(self):
        n = self.u16()
        if n % 2:
            raise ItemData1275Error('1275 UTF-16LE 長度不是偶數')
        try:
            return self.take(n).decode('utf-16-le')
        except UnicodeError as exc:
            raise ItemData1275Error('1275 UTF-16LE 文字無法解碼') from exc


def parse_items_1275(raw):
    """Return complete combat/gear fields and conservative alchemy metadata."""
    r = _Reader(raw)
    count = r.i32()
    if not 1 <= count <= 20000:
        raise ItemData1275Error('1275 ItemData_C 物品數量無效')
    items, alchemy = {}, {}
    for _ in range(count):
        name, kind = r.unicode(), r.u8()
        kind_name, item_id = r.unicode(), r.u16()
        if not item_id or str(item_id) in items:
            raise ItemData1275Error('1275 物品 ID 重複或為零')
        order, icon_id, shop_icon_id = r.u16(), r.u16(), r.u16()
        pictures = [r.u16() for _ in range(4)]
        attributes = [{'kind': r.u16(), 'effect': r.u8(), 'value': r.i32()}
                      for _ in range(2)]
        material, level, fit_type, special = r.u8(), r.u8(), r.u8(), r.u8()
        r.take(64)  # 4 body-type palettes x 4 UInt32
        open_used, need_level = r.u8(), r.u8()
        price, sell_price, gender, restrict = r.u32(), r.u32(), r.u8(), r.u16()
        threshold, element, element_value = r.u32(), r.u8(), r.u32()
        skill_link = r.u16()
        spares = [r.u16() for _ in range(5)]
        description = r.unicode()
        dimensions = [r.u8() for _ in range(3)]
        evolution, width, height, show_order = r.u16(), r.u8(), r.u8(), r.u8()
        is_generator = r.u16()
        pic_left_id, pic_right_id, assign_id = r.u16(), r.u16(), r.u16()
        put_kind, apanage, apanage2 = r.u8(), r.u8(), r.u8()
        special_effect_reference, weapon_position_group_id, furniture_kind = (
            r.u8(), r.u8(), r.u8())
        item_available_time, item_limited_time, use_count, present_id, purple_point = (
            r.u16() for _ in range(5))
        r.take(24)  # 6 reserved UInt32
        reference_id, model_id, flags, flags2 = r.u16(), r.u16(), r.u8(), r.u8()
        hair_model_kind, special_furniture_kind, furniture_parameter, can_use_roles = (
            r.u8(), r.u8(), r.u8(), r.u8())
        library_mark_id, place_z = r.u16(), r.u8()
        suit_model_ids = [r.u16() for _ in range(5)]
        can_buy_materials = r.u8()
        firing_id, style_bank_id, style_bank_sort_id = r.u16(), r.u16(), r.u16()
        if not name.strip() or width > 64 or height > 64:
            raise ItemData1275Error('1275 物品名稱或尺寸異常：' + str(item_id))
        sid = str(item_id)
        items[sid] = {
            'id': item_id, 'name': name, 'kind_name': kind_name,
            'kind': kind, 'fit_type': fit_type, 'special': special,
            'restrict': restrict, 'attributes': attributes,
            'skill_link': skill_link, 'order': order, 'icon_id': icon_id,
            'shop_icon_id': shop_icon_id, 'pictures': pictures,
            'level': level, 'need_level': need_level, 'open_used': open_used,
            'price': price, 'sell_price': sell_price, 'gender': gender,
            'threshold': threshold, 'element': element, 'element_value': element_value,
            'description': description, 'dimensions': dimensions,
            'width': width, 'height': height, 'evolution': evolution,
            'show_order': show_order, 'is_generator': is_generator,
            'pic_left_id': pic_left_id, 'pic_right_id': pic_right_id,
            'assign_id': assign_id, 'put_kind': put_kind, 'apanage': apanage,
            'apanage2': apanage2, 'special_effect_reference': special_effect_reference,
            'weapon_position_group_id': weapon_position_group_id,
            'furniture_kind': furniture_kind, 'item_available_time': item_available_time,
            'item_limited_time': item_limited_time, 'use_count': use_count,
            'present_id': present_id, 'purple_point': purple_point,
            'reference_id': reference_id, 'model_id': model_id, 'flags': flags,
            'flags2': flags2, 'hair_model_kind': hair_model_kind,
            'special_furniture_kind': special_furniture_kind,
            'furniture_parameter': furniture_parameter, 'can_use_roles': can_use_roles,
            'library_mark_id': library_mark_id, 'place_z': place_z,
            'suit_model_ids': suit_model_ids, 'can_buy_materials': can_buy_materials == 1,
            'firing_id': firing_id, 'style_bank_id': style_bank_id,
            'style_bank_sort_id': style_bank_sort_id,
        }
        alchemy[sid] = {'level': level, 'material': material, 'spares': spares,
                         # Eight test-only 1275 items declare 0x0 cells. Treat
                         # them as occupying at least one cell; never undercount.
                         'width': max(1, width), 'height': max(1, height)}
    if r.pos != len(raw):
        raise ItemData1275Error('1275 ItemData_C 尾端有無法識別的資料')
    return {'source_revision': 1275, 'items': items, 'alchemy': alchemy}


def activate_1275_items(runtime):
    """Replace shared item + alchemy maps in place after full pre-validation."""
    if getattr(runtime, 'revision', None) != 1275:
        raise ItemData1275Error('拒絕載入非1275物品來源')
    source = getattr(runtime, 'item_catalog', None)
    if not isinstance(source, dict) or source.get('source_revision') != 1275:
        raise ItemData1275Error('缺少1275完整物品定義')
    items, meta = source.get('items'), source.get('alchemy')
    if not isinstance(items, dict) or not items or not isinstance(meta, dict):
        raise ItemData1275Error('1275 物品定義及煉金索引格式錯誤')
    if items.keys() != meta.keys():
        raise ItemData1275Error('1275 物品與煉金 ID 集合不一致')
    for sid, row in items.items():
        if (not isinstance(sid, str) or not sid.isdecimal()
                or not isinstance(row, dict) or row.get('id') != int(sid)
                or not isinstance(row.get('name'), str) or not row['name'].strip()
                or not isinstance(row.get('attributes'), list)
                or len(row['attributes']) != 2
                or any(type(row.get(k)) is not int for k in
                       ('kind', 'fit_type', 'special', 'restrict', 'skill_link', 'icon_id'))):
            raise ItemData1275Error('1275 物品戰鬥欄位無效')
        entry = meta[sid]
        if (not isinstance(entry, dict) or not isinstance(entry.get('spares'), list)
                or len(entry['spares']) != 5
                or any(type(entry.get(k)) is not int or entry[k] < 1
                       for k in ('width', 'height'))):
            raise ItemData1275Error('1275 物品煉金欄位無效')
    from wlre.services.items.catalog import CAT
    from wlre.services.items.alchemy import META
    # Existing UI and battle modules import these dicts by reference.
    CAT['items'].clear()
    CAT['items'].update(items)
    META.clear()
    META.update(meta)
    return len(items)
