"""Display names from verified current ScenesData_C + TextData_C; IDs stay numeric."""
from wlre.paths import RESOURCE_ROOT
import json
import re
from functools import lru_cache


@lru_cache(maxsize=1)
def data():
    from wlre.services.world.runtime_1275 import baseline_revision, active_runtime
    if baseline_revision() == '1275':
        try:
            active = active_runtime()
        except (OSError, ValueError):
            # Before local resources are installed, show no unverified old maps.
            return {'maps': {}, 'models': {}}
        maps, models = {}, {}
        for sid, stage in active.stages.items():
            if not isinstance(stage, dict):
                continue
            name = active.texts.get(stage.get('name_id'))
            if not isinstance(name, str) or not name.strip():
                continue
            maps[str(sid)] = name
            model = stage.get('model_id')
            if type(model) is int and model >= 0:
                models.setdefault(str(model), name)
        return {'maps': maps, 'models': models}
    return json.loads(RESOURCE_ROOT.joinpath('map_names.json').read_text(encoding='utf8'))


def parse_map_id(value):
    text=str(value).strip()
    match=re.search(r'[（(](\d+)[）)]\s*$',text)
    if match:return int(match.group(1))
    if re.fullmatch(r'[Mm]?\d+',text):return int(text.lstrip('Mm'))
    raise ValueError('請輸入地圖 ID 或選擇「地圖名稱(地圖ID)」。')


def map_label(value):
    sid=parse_map_id(value)
    return f"{data()['maps'].get(str(sid),'未知地圖')}({sid})"


def model_label(value):
    sid=parse_map_id(value)
    return f"{data()['models'].get(str(sid),'未命名場景')}({sid})"


def map_choices():
    return [map_label(i) for i in sorted(data()['maps'],key=int)]
