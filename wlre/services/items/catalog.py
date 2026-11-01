"""Read-only official combat item and skill catalog."""
import json
from wlre.paths import RESOURCE_ROOT
from wlre.storage.bundled_database import load_bundled_json
CAT=load_bundled_json('combat_catalog.json', root=RESOURCE_ROOT)

def item_name(item_id):return CAT['items'].get(str(item_id),{}).get('name',f'物品{item_id}')
def skill_name(skill_id):return CAT['skills'].get(str(skill_id),{}).get('name',f'技能{skill_id}')


def item_display_name(item_id):
    """UI 名稱統一優先使用經獨立驗證的 1275 Runtime。

    SQLite 與自動候選資料不覆蓋正式版本名稱；缺正式來源時，
    僅可使用自動候選的唯讀名稱作顯示回退，且絕不授權物品操作。
    """
    if type(item_id) is int and item_id > 0:
        from wlre.services.world.runtime_1275 import (
            Runtime1275Unavailable, baseline_revision)
        try:
            if baseline_revision() == '1275':
                from wlre.services.world.catalog_source_policy import official_runtime
                item = official_runtime('items').items.get(item_id)
                if (type(item) is dict and isinstance(item.get('name'), str)
                        and item['name'].strip()):
                    return item['name']
        except (Runtime1275Unavailable, OSError, ValueError, KeyError):
            pass
    if type(item_id) is int and 1 <= item_id <= 65535:
        from wlre.services.world.auto_candidate_reader import candidate_item_name
        preview_name = candidate_item_name(item_id)
        if isinstance(preview_name, str) and preview_name.strip():
            return preview_name
    return item_name(item_id)


def verified_item_metadata(item_id):
    """Return audited 1275 ItemData_C display metadata; never inferred effects.

    The official current preview includes price, restrictions and required
    level but NOT a fully reviewed 1275 combat/heal effect table. A missing
    formal catalog returns None rather than labeling 1262 metadata as 1275.
    """
    if type(item_id) is not int or not 1 <= item_id <= 65535:
        return None
    from wlre.services.world.runtime_1275 import (
        Runtime1275Unavailable, baseline_revision, active_runtime)
    try:
        if baseline_revision() != '1275':
            return None
        item = active_runtime().items.get(item_id)
    except (Runtime1275Unavailable, OSError, ValueError, KeyError):
        return None
    if (type(item) is not dict
            or type(item.get('name')) is not str or not item['name'].strip()
            or any(type(item.get(name)) is not int for name in
                   ('price', 'sell_price', 'restrict', 'open_used', 'need_level'))):
        return None
    return {'item_id': item_id, 'name': item['name'],
            'base_price': item['price'], 'base_sell_price': item['sell_price'],
            'npc_sale_allowed': (item['restrict'] & 0x10) == 0,
            'need_level': item['need_level'], 'open_used': item['open_used'],
            'source_revision': 1275, 'effects_verified': False,
            'can_send_packets': False}
