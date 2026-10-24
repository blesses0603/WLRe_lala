"""Read-only official combat item and skill catalog."""
import json
from wlre.paths import RESOURCE_ROOT
CAT=json.loads(RESOURCE_ROOT.joinpath('combat_catalog.json').read_text(encoding='utf8'))

def item_name(item_id):
    """Use verified current-revision names, never label 1275 items from 1262."""
    unknown = f'物品{item_id}'
    from wlre.services.world.runtime_1275 import baseline_revision, active_runtime
    try:
        revision = baseline_revision()
    except (OSError, ValueError):
        # An unreadable baseline must never authorize legacy item names.
        return unknown
    if revision == '1275':
        try:
            row = active_runtime().items.get(int(item_id))
        except (OSError, ValueError, TypeError):
            # Before installing validated 1275 archives, show only the ID.
            return unknown
        if isinstance(row, dict):
            name = row.get('name')
            if isinstance(name, str) and name.strip():
                return name
        return unknown
    return CAT['items'].get(str(item_id), {}).get('name', unknown)
def skill_name(skill_id):return CAT['skills'].get(str(skill_id),{}).get('name',f'技能{skill_id}')

