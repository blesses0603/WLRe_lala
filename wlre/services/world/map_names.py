"""Display names from 1262 ScenesData_C + TextData_C; IDs stay numeric."""
from wlre.paths import RESOURCE_ROOT
import json
import re
from functools import lru_cache


@lru_cache(maxsize=1)
def data():
    from wlre.storage.bundled_database import load_bundled_json
    return load_bundled_json('map_names.json', root=RESOURCE_ROOT)


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
