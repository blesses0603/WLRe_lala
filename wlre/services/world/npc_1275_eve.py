"""Strict, offline-only reader for validated 1275 Eve NPC/event choice indexes.

No packets, runtime index switching, or implied NPC trade permissions.
"""
import gzip
import hashlib
import io
import json
from zipfile import ZipFile

VERSION = 1275
SOURCE_SHA256 = 'f5fc56b1d6cf7c00dd20b2f35c04b4cbc60c92ccdb6085fbe465c7e6526745ad'
FILES = {
    'npc_event_index_1275.json.gz': ('EventData.NewNpc', 165084, 'c56d043afba15974c56f8ff104870e5ae62d989bc62741689196234ef8c9d24c', 10975),
    'npc_interact_1275.json.gz': ('EventData.NewInteract', 36096, 'fe8741d0cb7528bf0b667d179e96901dd5df422dd0d02c591da922da6a992f9a', 1634),
}


def verify_file(name, raw):
    if name not in FILES or type(raw) is not bytes:
        raise ValueError('未知的 1275 Eve 索引')
    source, size, digest, count = FILES[name]
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(name + ' SHA-256 / 長度不符')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
        content = f.read(8*1024*1024+1)
    if len(content) > 8*1024*1024:
        raise ValueError('Eve 索引解壓縮過大')
    doc = json.loads(content.decode('utf-8'))
    if (type(doc) is not dict or doc.get('version') != VERSION
            or doc.get('source') != source
            or doc.get('eve_sha256') != SOURCE_SHA256
            or doc.get('scene_count') != 1262
            or type(doc.get('scenes')) is not dict
            or len(doc['scenes']) != (1262 if source == 'EventData.NewNpc' else 507)
            or doc.get('npc_count' if source == 'EventData.NewNpc' else 'interact_count') != count):
        raise ValueError('Eve 索引來源、版本或總數不符')
    if source == 'EventData.NewInteract':
        if (doc.get('interact_scene_count') != 507
                or doc.get('form_kind_counts') != {'1': 1569, '2': 19, '3': 46}):
            raise ValueError('Eve 選單分類數不符')
    total=0
    for scene, rows in doc['scenes'].items():
        if (type(scene) is not str or not scene.isdecimal() or str(int(scene)) != scene
                or not 0 <= int(scene) <= 65535 or type(rows) is not list or len(rows) > 4096):
            raise ValueError('Eve 場景資料不合法')
        seen=set()
        for row in rows:
            if (type(row) is not dict or type(row.get('index')) is not int
                    or not 0 <= row['index'] <= 65535 or row['index'] in seen):
                raise ValueError('Eve 事件索引重複或錯誤')
            seen.add(row['index'])
            if source == 'EventData.NewNpc':
                if (type(row.get('npc_id')) is not int or not 1 <= row['npc_id'] <= 0xffffffff
                        or any(type(row.get(k)) is not int or not 0 <= row[k] <= 0xffffffff
                               for k in ('x','y','event_count'))
                        or not isinstance(row.get('event_ids'), list)
                        or row['event_count'] != len(row['event_ids'])
                        or any(type(v) is not int or not 0 <= v <= 255 for v in row['event_ids'])):
                    raise ValueError('Eve NPC 資料欄位錯誤')
            else:
                if (type(row.get('form_kind')) is not int or row['form_kind'] not in (1,2,3)
                        or type(row.get('link_number')) is not int
                        or not isinstance(row.get('items'),list) or len(row['items'])>255):
                    raise ValueError('Eve 選單欄位不合法')
                for item in row['items']:
                    if (type(item) is not dict or any(type(item.get(k)) is not int for k in
                        ('id','text_id','database_kind','kind')) or not 0 <= item['id'] <= 255
                        or not 0 <= item['text_id'] <= 65535
                        or not 0 <= item['database_kind'] <= 255 or not 0 <= item['kind'] <= 255):
                        raise ValueError('Eve 選單項目無效')
        total += len(rows)
    if total != count:
        raise ValueError('Eve 實際總數與宣告不符')
    return doc


def read_verified_zip(path):
    """Reject member injection, never unzip entries into arbitrary locations."""
    with ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=3 or set(names)!=set(FILES)|{'README.txt'}:
            raise ValueError('1275 Eve 索引 ZIP 多檔、缺檔或含重複條目')
        return {name:verify_file(name,z.read(name)) for name in FILES}


def scene_npcs(verified, scene):
    """Verified read-only roster, not authority to send C20 network commands."""
    return tuple(verified['npc_event_index_1275.json.gz']['scenes'].get(str(scene), ()))


def scene_choices(verified, scene):
    return tuple(verified['npc_interact_1275.json.gz']['scenes'].get(str(scene), ()))
