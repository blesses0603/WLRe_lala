"""Read official AdventureData_C/AdventureLvData_C using the 1262 Lua layout."""
import hashlib
import json
import os
from pathlib import Path

from wlre.network.wire import Reader, ProtocolError
from wlre.paths import RESOURCE_ROOT
from wlre.storage.atomic import write_json


def data_root():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.config') / 'WLRE_LaLa'


def parse_catalog(tasks_data, levels_data):
    r = Reader(tasks_data)
    tasks = {}
    count = r.i32()
    if not 1 <= count <= 65535:
        raise ProtocolError('遠征任務資料筆數錯誤')
    for _ in range(count):
        q = {'id': r.u16(), 'area': r.u8(), 'area_name': r.u32(), 'difficulty': r.u8(),
             'name_id': r.u32(), 'description_id': r.u32(), 'minutes': r.u16(),
             'faith_cost': r.u8(), 'success_rate': r.u16(),
             'condition': [r.u16(), r.u16(), r.u16()]}
        r.take(4 * 8)  # four recommendation conditions
        r.u32()  # expedition experience
        q['rewards'] = [{'kind': r.u8(), 'id': r.u32(), 'value': r.u32()} for _ in range(3)]
        q['special_rate'] = r.u16()
        q['special_reward'] = {'kind': r.u8(), 'id': r.u32(), 'value': r.u32()}
        r.i32()  # character experience
        if not q['id'] or str(q['id']) in tasks or not q['minutes'] or q['faith_cost'] > 100:
            raise ProtocolError('遠征任務資料內容錯誤')
        tasks[str(q['id'])] = q
    r.end()
    r = Reader(levels_data)
    count = r.i32()
    if not 1 <= count <= 255:
        raise ProtocolError('遠征等級資料筆數錯誤')
    levels = {}
    for _ in range(count):
        level = r.u8()
        r.u32(); r.u32()
        value = {'teams': r.u8(), 'difficulty': r.u8(), 'reduction': r.u16()}
        r.u8(); r.u8()
        if str(level) in levels or not 0 <= value['teams'] <= 7 or value['reduction'] > 1000:
            raise ProtocolError('遠征等級資料內容錯誤')
        levels[str(level)] = value
    r.end()
    return {'tasks': tasks, 'levels': levels, 'source_sha256': {
        'AdventureData_C': hashlib.sha256(tasks_data).hexdigest(),
        'AdventureLvData_C': hashlib.sha256(levels_data).hexdigest()}}


def import_catalog(tasks_path, levels_path):
    value = parse_catalog(Path(tasks_path).read_bytes(), Path(levels_path).read_bytes())
    write_json(data_root() / 'expedition_catalog.json', value)
    return value


def load_catalog():
    local = data_root() / 'expedition_catalog.json'
    bundled = RESOURCE_ROOT / 'expedition_catalog.json'
    path = local if local.is_file() else bundled
    if not path.is_file():
        return {'tasks': {}, 'levels': {}}
    return json.loads(path.read_text(encoding='utf8'))
