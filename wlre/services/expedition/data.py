"""Read official AdventureData_C/AdventureLvData_C using the 1262 Lua layout."""
from wlre.storage.paths import data_root as user_data_root
import hashlib
import json
import os
import struct
from pathlib import Path

from wlre.network.wire import Reader, ProtocolError
from wlre.paths import RESOURCE_ROOT


def data_root():
    return user_data_root()


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
        q['recommendations'] = [{'condition': [r.u16(), r.u16(), r.u16()], 'bonus': r.u16()} for _ in range(4)]
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


def parse_text_data(text_data):
    """Strictly read official TextData_C v1; no guessed fields or fallback.

    Used by the expedition name mapper and the read-only automatic asset
    inventory. An unknown binary layout fails closed without overwriting
    any previously reviewed runtime text.
    """
    if type(text_data) is not bytes or not 4 < len(text_data) <= 16 * 1024 * 1024:
        raise ProtocolError('文字資料來源缺失或大小不合法')
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
    return texts


def attach_names(catalog, text_data):
    """Bind mission names only from same official TextData_C bytes."""
    texts = parse_text_data(text_data)
    tasks = {}
    for sid, quest in catalog['tasks'].items():
        name = texts.get(quest['name_id'])
        if not name:
            raise ProtocolError(f'官方文字資料缺少任務名稱：{sid}')
        tasks[sid] = {**quest, 'name': name, 'area_label': texts.get(quest['area_name'], '')}
    return {**catalog, 'tasks': tasks, 'source_sha256': {
        **catalog.get('source_sha256', {}), 'TextData_C': hashlib.sha256(text_data).hexdigest()}}


def parse_npcs(npc_data, career_data):
    """NpcData.New fixed numeric fields, and NpcCareerData.LoadData mapping."""
    r = Reader(career_data)
    careers = {}
    for _ in range(r.i32()):
        record = r.take(17)
        original, career = struct.unpack_from('<HH', record, 2)
        if career in careers: raise ProtocolError('轉職夥伴對照重複')
        careers[career] = original
    r.end()
    r = Reader(npc_data)
    count = r.i32()
    if not 1 <= count <= 65535: raise ProtocolError('夥伴資料筆數錯誤')
    npcs = {}
    for _ in range(count):
        for _ in range(2):
            size = r.u16()
            if size % 2: raise ProtocolError('夥伴名稱長度錯誤')
            r.take(size).decode('utf-16-le')
        fields = r.take(203)
        sid = struct.unpack_from('<H', fields, 1)[0]
        npcs[str(sid)] = {'element': fields[74], 'kind': fields[106], 'original': careers.get(sid, sid)}
    r.end()
    return npcs


# These two official TextAssets are byte-identical in the audited 1262/1275
# sources. NPC and localization tables changed and must not be borrowed from
# bundled 1262 catalogs for a 1275 dispatch decision.
ADVENTURE_1275_SHA256 = 'e240dbc011fe213f2a5d907b9d02281ab2417b764caecd2fd222f99faedb59e8'
ADVENTURE_LEVEL_1275_SHA256 = '98b8359741f2e67fe7a15214c6a6b1c6495977a00d6c666beed9d129f4d520d4'


def load_verified_1275_catalog():
    """Load expedition rows exclusively from the independently pinned 1275 ZIP.

    All 160 archive files must pass the repository's fixed manifest and
    per-file hashes before extracting expedition data. The 1275 NPC and text
    sources are independently bound to that manifest as well. This provides
    verified static data, NOT protocol/dispatch compatibility approval.
    """
    from zipfile import ZipFile
    from wlre.services.world.game_data_1275 import read_manifest, verify_archive
    from wlre.services.world.runtime_1275 import (
        Runtime1275Unavailable, baseline_revision, active_runtime,
        resource_dir, DATA_FILE,
    )

    if baseline_revision() != '1275':
        raise Runtime1275Unavailable('正式資源基準不是 1275')
    runtime = active_runtime()
    if runtime.revision != 1275:
        raise Runtime1275Unavailable('遠征資料來源版本不符合 1275')
    path = resource_dir() / DATA_FILE
    # Do not trust path-only classification, self-computed candidate hashes
    # or an unchecked ZIP as a gameplay-ready expedition catalog.
    verify_archive(path)
    with ZipFile(path) as archive:
        manifest = read_manifest(archive)
        tables = {}
        for table in ('AdventureData_C', 'AdventureLvData_C',
                      'NpcData_C', 'NpcCareerData_C'):
            matches = [name for name, row in manifest['files'].items()
                       if row.get('kind') == 'raw_table' and row.get('table') == table]
            if len(matches) != 1:
                raise ValueError('1275 遠征資料表缺失或名稱重複：' + table)
            name = matches[0]
            raw = archive.read(name)
            row = manifest['files'][name]
            # Recheck after verification to prevent a replaced ZIP from
            # supplying different bytes between the two file opens.
            if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('1275 遠征原始表二次校驗失敗：' + table)
            tables[table] = raw

    if (hashlib.sha256(tables['AdventureData_C']).hexdigest() != ADVENTURE_1275_SHA256
            or hashlib.sha256(tables['AdventureLvData_C']).hexdigest()
            != ADVENTURE_LEVEL_1275_SHA256):
        raise ValueError('遠征任務與等級表的已審核來源指紋不符')

    result = parse_catalog(tables['AdventureData_C'], tables['AdventureLvData_C'])
    if len(result['tasks']) != 260 or len(result['levels']) != 10:
        raise ValueError('1275 遠征任務／等級筆數不符')
    npcs = parse_npcs(tables['NpcData_C'], tables['NpcCareerData_C'])
    if len(npcs) != 7561:
        raise ValueError('1275 夥伴職業／元素索引筆數不符')

    texts = runtime.texts
    if type(texts) is not dict:
        raise ValueError('1275 文字索引格式不符')
    named = {}
    for key, quest in result['tasks'].items():
        name = texts.get(quest['name_id'])
        area = texts.get(quest['area_name'], '')
        if (not isinstance(name, str) or not name.strip()
                or not isinstance(area, str)
                or len(name) > 8192 or len(area) > 8192):
            raise ValueError('1275 遠征任務缺少已驗證的名稱／地區文字：' + key)
        named[key] = {**quest, 'name': name, 'area_label': area}
    return {**result, 'tasks': named, 'npcs': npcs, 'revision': 1275,
            'source_kind': 'verified_1275_full_archive',
            'source_sha256': {
                **result['source_sha256'],
                'NpcData_C': hashlib.sha256(tables['NpcData_C']).hexdigest(),
                'NpcCareerData_C': hashlib.sha256(tables['NpcCareerData_C']).hexdigest(),
            }}


def load_active_catalog():
    """Operation-safe source, distinct from the bundled legacy display data.

    Missing or incompatible 1275 formal inputs are *not* allowed to silently
    fall back to 1262, especially for success probabilities and team choice.
    """
    from wlre.services.world.runtime_1275 import baseline_revision
    if baseline_revision() == '1275':
        return load_verified_1275_catalog()
    return load_catalog()
