"""Read-only official combat item and skill catalog."""
import json
from wlre.paths import RESOURCE_ROOT
CAT=json.loads(RESOURCE_ROOT.joinpath('combat_catalog.json').read_text(encoding='utf8'))

def item_name(item_id):return CAT['items'].get(str(item_id),{}).get('name',f'物品{item_id}')
def skill_name(skill_id):return CAT['skills'].get(str(skill_id),{}).get('name',f'技能{skill_id}')


def item_display_name(item_id):
    """Prefer independently release-pinned 1275 ItemData names for UI only.

    This never changes skill/item effects, bag counts or any packet decision.
    When the complete pinned runtime is absent, retain the previous display
    name; screens separately report the classification/candidate status.
    """
    if type(item_id) is int and item_id > 0:
        from wlre.services.world.runtime_1275 import (
            Runtime1275Unavailable, active_runtime, baseline_revision)
        try:
            if baseline_revision() == '1275':
                item = active_runtime().items.get(item_id)
                if (type(item) is dict and
                        isinstance(item.get('name'), str) and item['name'].strip()):
                    return item['name']
        except (Runtime1275Unavailable, OSError, ValueError, KeyError):
            pass
    return item_name(item_id)
