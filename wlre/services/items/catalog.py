"""Read-only official combat item and skill catalog."""
import json
from wlre.paths import RESOURCE_ROOT
CAT=json.loads(RESOURCE_ROOT.joinpath('combat_catalog.json').read_text(encoding='utf8'))

def item_name(item_id):return CAT['items'].get(str(item_id),{}).get('name',f'物品{item_id}')
def skill_name(skill_id):return CAT['skills'].get(str(skill_id),{}).get('name',f'技能{skill_id}')

