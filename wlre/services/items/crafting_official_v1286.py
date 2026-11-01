"""Official 1286 recipe identities and C64 wire formats.

This module does not approve a runtime or send packets. Callers must select
the protocol only after the current official versions have been verified.
"""
from collections import defaultdict
from copy import deepcopy

from wlre.network.wire import Packet, ProtocolError, Reader, Writer


class RecipeCatalog:
    def __init__(self, recipes):
        self.by_recipe = {}
        self.by_item = defaultdict(list)
        for raw in recipes:
            if type(raw) is not dict:
                raise ValueError('Invalid recipe')
            recipe_id, item_id = raw.get('recipe_id'), raw.get('item_id')
            if (type(recipe_id) is not int or not 1 <= recipe_id <= 65535
                    or type(item_id) is not int or not 1 <= item_id <= 65535
                    or recipe_id in self.by_recipe):
                raise ValueError('Invalid or duplicate recipe identity')
            row = deepcopy(raw)
            self.by_recipe[recipe_id] = row
            self.by_item[item_id].append(recipe_id)

    def get(self, recipe_id):
        value = self.by_recipe.get(recipe_id)
        return deepcopy(value) if value is not None else None

    def for_item(self, item_id):
        return [self.get(key) for key in self.by_item.get(item_id, ())]


def load_candidate_catalog(*, root=None):
    """Read recipes from the Launcher catalog; not a gameplay approval."""
    from pathlib import Path
    from wlre.storage.paths import data_root
    from wlre.services.world.launcher_catalog import read_launcher_status
    from wlre.services.world.resource_database import read_catalog_tables
    base = Path(root) if root is not None else data_root() / 'official_sync'
    receipt = read_launcher_status(root=base)
    if (not receipt or receipt.get('status') not in ('review_required', 'downloaded_unparsed')
            or not receipt.get('catalog_key')):
        raise ValueError('尚無可讀取的官方配方候選資料')
    path = base / 'derived_catalogs' / 'resource_inventory.sqlite3'
    rows = read_catalog_tables(path, receipt['catalog_key'], ['recipes'])['recipes']
    return RecipeCatalog(rows)


def compare_legacy_recipes(old_recipes, new_catalog):
    """Compare 1275 product-keyed recipes to 1286 recipe-keyed records.

    A product with multiple new recipes cannot be matched to a single legacy
    record without guessing, so it is explicitly reported as ambiguous.
    """
    if not isinstance(old_recipes, dict) or not isinstance(new_catalog, RecipeCatalog):
        raise ValueError('Invalid recipe catalogs')
    old = {}
    for key, row in old_recipes.items():
        if type(row) is not dict or type(row.get('item_id')) is not int or row['item_id'] in old:
            raise ValueError('Invalid legacy recipe identity')
        old[row['item_id']] = row
    fields = ('design_id', 'skill', 'tool_id', 'output', 'materials', 'seconds',
              'skill_level', 'suggest', 'time_id', 'limit_kind', 'mark_id', 'limit_times')
    added, changed, removed, unchanged, ambiguous = [], [], [], [], []
    for item_id in sorted(set(old) | set(new_catalog.by_item)):
        candidates = new_catalog.for_item(item_id)
        if item_id not in old:
            added.extend(r['recipe_id'] for r in candidates)
        elif not candidates:
            removed.append(item_id)
        elif len(candidates) > 1:
            ambiguous.append({'item_id': item_id, 'recipe_ids': [r['recipe_id'] for r in candidates]})
        else:
            new = candidates[0]
            if any(old[item_id].get(field) != new.get(field) for field in fields):
                changed.append(new['recipe_id'])
            else:
                unchanged.append(new['recipe_id'])
    return {'added': added, 'changed': changed, 'removed_legacy_item_ids': removed,
            'unchanged': unchanged, 'ambiguous': ambiguous}


def read_schedule_record(reader, catalog):
    index, recipe_id = reader.u8(), reader.u16()
    elapsed, count, base_time = reader.u32() / 1000, reader.u8(), reader.u32()
    if not index or not recipe_id or not count:
        raise ProtocolError('製作排程欄位無效')
    recipe = catalog.get(recipe_id)
    if recipe is None:
        raise ProtocolError('新版製作排程包含未知配方，請重新同步資源')
    return {'index': index, 'recipe_id': recipe_id, 'item_id': recipe['item_id'],
            'elapsed': elapsed, 'count': count, 'base_time': base_time}


def decode_schedule(packet, catalog):
    if packet.main != 64 or packet.sub not in (1, 16):
        raise ProtocolError('非新版製作排程封包')
    reader = Reader(packet.payload)
    if packet.sub == 16:
        row = read_schedule_record(reader, catalog)
        reader.end()
        return {'type': 'craft_added', 'row': row}
    if len(packet.payload) < 1 or (len(packet.payload) - 1) % 12:
        raise ProtocolError('製作排程長度不符')
    rows = [read_schedule_record(reader, catalog) for _ in range((len(packet.payload) - 1) // 12)]
    active = reader.u8()
    reader.end()
    if len({row['index'] for row in rows}) != len(rows):
        raise ProtocolError('製作排程索引重複')
    return {'type': 'craft_snapshot', 'rows': rows, 'active': active}


def build_add_packet(catalog, recipe_id, tool_index, count, allocations):
    """Build the observed 1286 wire payload without submitting it."""
    recipe = catalog.get(recipe_id)
    if recipe is None:
        raise ProtocolError('找不到新版配方')
    if recipe.get('read_only') is True or recipe.get('time_id') or recipe.get('limit_kind'):
        raise ProtocolError('限時或限制次數配方僅供查看')
    if type(count) is not int or not 1 <= count <= 255:
        raise ProtocolError('製作批數無效')
    if type(tool_index) is not int or not 0 <= tool_index <= 65535:
        raise ProtocolError('器具索引無效')
    if not isinstance(allocations, (tuple, list)) or len(allocations) > 255:
        raise ProtocolError('材料格數無效')
    writer = Writer().u16(tool_index).u16(recipe_id).u16(recipe['item_id']).u8(count).u8(len(allocations))
    for allocation in allocations:
        if (type(allocation) is not dict or type(allocation.get('index')) is not int
                or not 0 <= allocation['index'] <= 255 or type(allocation.get('count')) is not int
                or not 1 <= allocation['count'] <= 255):
            raise ProtocolError('材料資料無效')
        writer.u8(allocation['index']).u8(allocation['count'])
    return Packet(64, 1, writer.u16(0).u8(0).build())
