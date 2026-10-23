"""Official 1262 Eve interactDatas. Read-only until a verified index is present.

This catalogue is generated from Eve_1262.bundle (MD5 81af6903...).
Only normal formKind=1 and text-backed kind=3 buttons can be selected.
Never infer an option from names, map positions or generic TextData IDs.
"""
import gzip
import hashlib
import json
from pathlib import Path

from wlre.paths import RESOURCE_ROOT

NAME = 'npc_interact_1262.json.gz'
EXPECTED_SHA256 = '37bba3db9ec06cc4838bec99a2fb16d6b49f7064edcfc46e59bf30ac08888592'
EVE_MD5 = '81af690395d5e6a233afa9a664e2c555'
MAX_SIZE = 8 * 1024 * 1024


class NPCInteractIndex:
    def __init__(self, path=None):
        if path is None:
            from wlre.services.world.runtime_1275 import baseline_revision, active_runtime
            if baseline_revision() == '1275':
                self.path = None
                self.scenes = active_runtime().interact_index.scenes
                return
        self.path = Path(path) if path is not None else RESOURCE_ROOT / NAME
        self.scenes = {}
        if not self.path.is_file():
            if path is None:
                return  # Missing optional bundle means choices stay disabled.
            raise FileNotFoundError(self.path)
        raw = self.path.read_bytes()
        if len(raw) > 128 * 1024:
            raise ValueError('Eve NPC 選項索引壓縮檔異常過大')
        if path is None and hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
            raise ValueError('Eve NPC 選項索引 SHA-256 不符')
        with gzip.open(self.path, 'rb') as stream:
            content = stream.read(MAX_SIZE + 1)
        if len(content) > MAX_SIZE:
            raise ValueError('Eve NPC 選項索引解壓縮超出限制')
        doc = json.loads(content.decode('utf-8'))
        if (not isinstance(doc, dict) or doc.get('version') != 1262
                or doc.get('source') != 'EventData.NewInteract'
                or doc.get('bundle_md5') != EVE_MD5
                or doc.get('scene_count') != 1256
                or doc.get('interact_scene_count') != 505
                or doc.get('interact_count') != 1622
                or doc.get('footer_bytes_per_scene') != 44
                or doc.get('total_npc_count_checked') != 10879
                or doc.get('form_kind_counts') != {'1': 1557, '2': 19, '3': 46}
                or not isinstance(doc.get('scenes'), dict)
                or len(doc['scenes']) != 505):
            raise ValueError('NPC 選項索引資料來源、結構或統計不符')
        total = 0
        for scene, rows in doc['scenes'].items():
            if (not isinstance(scene, str) or not scene.isdecimal()
                    or not 0 <= int(scene) <= 65535
                    or str(int(scene)) != scene
                    or not isinstance(rows, list) or len(rows) > 1024):
                raise ValueError('NPC 選項場景資料格式無效')
            resolved = {}
            for row in rows:
                if (not isinstance(row, dict) or
                        type(row.get('index')) is not int or not 0 <= row['index'] <= 65535
                        or type(row.get('form_kind')) is not int or row['form_kind'] not in (1, 2, 3)
                        or type(row.get('link_number')) is not int or not 0 <= row['link_number'] <= 65535
                        or not isinstance(row.get('items'), list) or len(row['items']) > 255
                        or row['index'] in resolved):
                    raise ValueError('Eve NPC 選項格式或索引重複')
                for item in row['items']:
                    if (not isinstance(item, dict)
                            or any(type(item.get(k)) is not int for k in
                                   ('id', 'text_id', 'database_kind', 'kind'))
                            or not 0 <= item['id'] <= 255
                            or not 0 <= item['text_id'] <= 65535
                            or not 0 <= item['database_kind'] <= 255
                            or not 0 <= item['kind'] <= 255):
                        raise ValueError('Eve NPC 子選項格式錯誤')
                resolved[row['index']] = row
                total += 1
            self.scenes[int(scene)] = resolved
        if total != 1622:
            raise ValueError('Eve NPC 選項總數不一致')

    def get(self, scene, interact_index):
        if type(scene) is not int or type(interact_index) is not int:
            return None
        row = self.scenes.get(scene, {}).get(interact_index)
        if getattr(self, 'path', False) is None and row is not None:  # Pinned 1275 data
            from copy import deepcopy
            return deepcopy(row)
        return row

    def choices(self, scene, interact_index, talks):
        """Render ONLY normal verified 0-based choice rows; shops are blocked."""
        row = self.get(scene, interact_index)
        if row is None or row['form_kind'] != 1 or not isinstance(talks, dict):
            return None
        headers = [e for e in row['items'] if e['kind'] == 1]
        options = [e for e in row['items'] if e['kind'] == 3]
        if (len(headers) != 1 or not 1 <= len(options) <= 10
                or any(e['kind'] not in (1, 3, 4) for e in row['items'])
                or any(e['database_kind'] != 1 for e in headers + options)):
            return None
        heading = talks.get(headers[0]['text_id'])
        if not isinstance(heading, str):
            return None
        display = []
        for pos, item in enumerate(options):
            content = talks.get(item['text_id'])
            if not isinstance(content, str) or not content.strip():
                return None
            display.append({'choice': pos, 'text_id': item['text_id'], 'text': content})
        return {'scene': scene, 'index': interact_index, 'title': heading,
                'form_kind': 1, 'options': display}
