"""Read official AdventureData_C/AdventureLvData_C using the 1262 Lua layout."""
import hashlib
import json
import os
from pathlib import Path

from wlre.network.wire import Reader, ProtocolError
from wlre.paths import RESOURCE_ROOT


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
        q['expedition_exp'] = r.u32()
        q['rewards'] = [{'kind': r.u8(), 'id': r.u32(), 'value': r.u32()} for _ in range(3)]
        q['special_rate'] = r.u16()
        q['special_reward'] = {'kind': r.u8(), 'id': r.u32(), 'value': r.u32()}
        q['exp'] = r.i32()
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


def load_catalog():
    path = RESOURCE_ROOT / 'expedition_catalog.json'
    if not path.is_file():
        return {'tasks': {}, 'levels': {}}
    return json.loads(path.read_text(encoding='utf8'))


def attach_names(catalog, text_data):
    """Data.OnLoadTextData: u32 key, u16 byte length, UTF-16LE text."""
    r = Reader(text_data)
    count = r.i32()
    if not 1 <= count <= 1000000:
        raise ProtocolError('文字資料筆數錯誤')
    texts = {}
    for _ in range(count):
        key, size = r.u32(), r.u16()
        if size % 2 or key in texts:
            raise ProtocolError('文字資料長度或識別碼錯誤')
        try:
            texts[key] = r.take(size).decode('utf-16-le')
        except UnicodeDecodeError as exc:
            raise ProtocolError('文字資料編碼錯誤') from exc
    r.end()
    tasks = {}
    for sid, quest in catalog['tasks'].items():
        name = texts.get(quest['name_id'])
        if not name:
            raise ProtocolError(f'官方文字資料缺少任務名稱：{sid}')
        tasks[sid] = {**quest, 'name': name, 'area_label': texts.get(quest['area_name'], '')}
    return {**catalog, 'tasks': tasks, 'source_sha256': {
        **catalog.get('source_sha256', {}), 'TextData_C': hashlib.sha256(text_data).hexdigest()}}
