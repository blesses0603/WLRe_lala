"""Account/server-scoped UI data, private storage; never credentials or auto-start."""
import json
from pathlib import Path
from wlre.storage.atomic import write_json, file_lock
from wlre.services.items.crafting import RECIPES
from wlre.services.items.crafting_plan import validate_rows


def defaults(): return {'favorites': [], 'plan': []}


def validate(value):
    if not isinstance(value, dict) or set(value) - {'favorites', 'plan'}: raise ValueError('偏好格式錯誤')
    ids = value.get('favorites', [])
    if (not isinstance(ids, list) or len(ids) > 100 or
            any(type(sid) is not int or str(sid) not in RECIPES for sid in ids)):
        raise ValueError('收藏配方無效，最多 100 項')
    return {'favorites': list(dict.fromkeys(ids)), 'plan': validate_rows(value.get('plan', []))}


def path(base, key): return Path(base) / 'mobile' / (key + '.json')


def load(base, key):
    file = path(base, key)
    with file_lock(file):
        if not file.exists(): return defaults()
        data = json.loads(file.read_text(encoding='utf8'))
        if data.get('version') != 1: raise ValueError('偏好版本不支援')
        return validate(data['preferences'])


def save(base, key, value):
    value = validate(value); file = path(base, key)
    with file_lock(file): write_json(file, {'version': 1, 'preferences': value})
    return value
