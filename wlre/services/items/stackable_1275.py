"""Official 1275 ItemData.CanOverlap compatibility for inventory S23 records.

Transcribed from verified Lua/Data/ItemData.lua CanOverlap and helper functions
(IsEquipItemId, IsTrafficTool, IsTrafficOrgTool, IsEggItem, IsTimeItem,
IsLimitedItem, IsMagicBottle, IsEmblemItem). Never use 1262 stackability for
an active 1275 runtime.
"""
from __future__ import annotations

NEVER_STACK_IDS = frozenset((34106, 34152, 34163, 34164, 34168, 34180))
TRAFFIC_KINDS = frozenset((39, 58))
ITEM_EQUIP_RANGE = range(1, 7)
SPECIAL_FIT = 9
NO_STACK_FIT = 10
SACRED_EQUIP_FIT = 11
EMBLEM_KIND = 76
HEAL_SPECIAL = 151
REPAIR_SPECIAL = 130
MAGIC_BOTTLE_IDS = frozenset((34298, 34299))


class Stackable1275Error(ValueError):
    pass


def can_overlap_1275(row):
    """Return client 1275 stackability, using the *full* 1275 item definition."""
    if not isinstance(row, dict):
        raise Stackable1275Error('1275 堆疊判定缺少完整物品記錄')
    keys = ('id', 'fit_type', 'kind', 'special', 'use_count',
            'item_available_time', 'item_limited_time', 'flags2')
    if any(type(row.get(k)) is not int for k in keys):
        raise Stackable1275Error('1275 堆疊欄位不完整')
    attrs = row.get('attributes')
    if not isinstance(attrs, list) or len(attrs) != 2 or any(
            not isinstance(a, dict) or type(a.get('kind')) is not int
            for a in attrs):
        raise Stackable1275Error('1275 堆疊缺少物品屬性欄位')

    sid, fit = row['id'], row['fit_type']
    if fit == NO_STACK_FIT or sid in NEVER_STACK_IDS:
        return False
    if fit in ITEM_EQUIP_RANGE or fit == SACRED_EQUIP_FIT:
        return False
    if row['kind'] in TRAFFIC_KINDS:
        return False
    # IsEggItem returns 255 for *every* fitType==Special (9).
    if fit == SPECIAL_FIT:
        return False
    if (1 <= fit < 8 or fit in (NO_STACK_FIT, SACRED_EQUIP_FIT)) and row['item_available_time']:
        return False
    # flags2 bit 0 maps to Lua isPVPTimeOver; includes seasonal items.
    if (1 <= fit < SPECIAL_FIT or fit in (NO_STACK_FIT, SACRED_EQUIP_FIT)) and (
            row['item_limited_time'] or row['flags2'] & 1):
        return False
    if (row['special'] == HEAL_SPECIAL and (
            attrs[0]['kind'] in (25, 26) or sid in MAGIC_BOTTLE_IDS)):
        return False
    if row['special'] == REPAIR_SPECIAL and row['use_count'] > 1:
        return False
    if row['kind'] == EMBLEM_KIND:
        return False
    return True


def build_1275_stackables(item_catalog):
    if (not isinstance(item_catalog, dict)
            or item_catalog.get('source_revision') != 1275
            or not isinstance(item_catalog.get('items'), dict)
            or not item_catalog['items']):
        raise Stackable1275Error('拒絕沒有完整1275 ItemData的堆疊來源')
    result = {}
    for sid, row in item_catalog['items'].items():
        if not isinstance(sid, str) or not sid.isdecimal() or (
                not isinstance(row, dict) or row.get('id') != int(sid)):
            raise Stackable1275Error('1275 物品ID不合法')
        result[sid] = can_overlap_1275(row)
    return result


def activate_1275_stackables(runtime):
    if getattr(runtime, 'revision', None) != 1275:
        raise Stackable1275Error('拒絕啟用非1275的堆疊表')
    source = getattr(runtime, 'item_catalog', None)
    derived = build_1275_stackables(source)
    from wlre.core.inventory_updates import STACKABLE
    STACKABLE.clear()
    STACKABLE.update(derived)
    return len(derived)
