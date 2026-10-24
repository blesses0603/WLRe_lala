"""Inspect pinned 1275 scene AstarPath Recast settings without enabling movement.

Reads local UnityFS scene bundles from the user's private archive. The embedded
AstarPath base64 ZIP contains graph0.json/meta.json settings only, NOT scanned
tiles, walkability triangles, or a verified network-coordinate mapping.

Optional dependency: pip install lz4
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import struct
from zipfile import ZipFile


class Recast1275Error(ValueError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class _Reader:
    def __init__(self, data, pos=0, *, endian='>'):
        self.data, self.pos, self.endian = data, pos, endian

    def take(self, amount):
        if amount < 0 or self.pos + amount > len(self.data):
            raise Recast1275Error('1275 Unity 資料超出檔案邊界')
        start = self.pos
        self.pos += amount
        return self.data[start:self.pos]

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack(self.endian + 'H', self.take(2))[0]

    def u32(self):
        return struct.unpack(self.endian + 'I', self.take(4))[0]

    def i32(self):
        return struct.unpack(self.endian + 'i', self.take(4))[0]

    def i16(self):
        return struct.unpack(self.endian + 'h', self.take(2))[0]

    def u64(self):
        return struct.unpack(self.endian + 'Q', self.take(8))[0]

    def i64(self):
        return struct.unpack(self.endian + 'q', self.take(8))[0]

    def cstring(self):
        try:
            end = self.data.index(b'\0', self.pos)
        except ValueError as exc:
            raise Recast1275Error('Unity 字串缺少結尾') from exc
        value = self.data[self.pos:end].decode('utf-8')
        self.pos = end + 1
        return value

    def align(self, n):
        self.pos = (self.pos + n-1)//n*n


def _decompress(source, mode, size):
    if not 0 <= size <= 256*1024*1024:
        raise Recast1275Error('Unity 解壓縮區塊過大')
    if mode == 0:
        result = source
    elif mode in (2, 3):
        try:
            from lz4.block import decompress
        except ImportError as exc:
            raise Recast1275Error('須先安裝 lz4：py -m pip install lz4') from exc
        result = decompress(source, uncompressed_size=size)
    else:
        raise Recast1275Error('無法讀取的 UnityFS 壓縮格式')
    if len(result) != size:
        raise Recast1275Error('UnityFS 解壓後長度不符')
    return result


def unity_nodes(raw):
    r = _Reader(raw)
    if r.cstring() != 'UnityFS':raise Recast1275Error('非預期的 UnityFS 檔案')
    version=r.u32()
    if version not in (6,7,8):raise Recast1275Error('不支援的 UnityFS 格式版本')
    r.cstring()
    r.cstring()
    declared = r.u64()
    zipped, expanded, flags = r.u32(), r.u32(), r.u32()
    if declared != len(raw) or zipped > len(raw):
        raise Recast1275Error('UnityFS Header 大小不符合')
    if version>=7:
        r.align(16)
    info_data = (raw[-zipped:] if flags & 0x80 else raw[r.pos:r.pos+zipped])
    blocks = _Reader(_decompress(info_data, flags & 63, expanded))
    blocks.take(16)
    block_count = blocks.u32()
    if not 0 < block_count <= 10000:
        raise Recast1275Error('UnityFS 區塊數量不合理')
    specs = [(blocks.u32(), blocks.u32(), blocks.u16())
             for _ in range(block_count)]
    files = []
    file_count = blocks.u32()
    if not 0 < file_count <= 10000:
        raise Recast1275Error('UnityFS 檔案數量不合理')
    for _ in range(file_count):
        files.append((blocks.u64(), blocks.u64(), blocks.u32(),
                      blocks.cstring()))
    if not flags & 0x80:
        r.take(zipped)
    if flags & 0x200:
        r.align(16)
    body = b''.join(_decompress(r.take(c), mode & 63, u)
                    for u, c, mode in specs)
    if len(body) > 256*1024*1024:
        raise Recast1275Error('UnityFS 解壓總量過大')
    nodes = []
    for start, size, _, name in files:
        if start+size > len(body):
            raise Recast1275Error('UnityFS CAB 範圍錯誤')
        nodes.append((name, body[start:start+size]))
    return nodes


def serialized_objects(asset):
    """Read v22 object records within metadata, never from the payload/padding."""
    if len(asset)<48 or struct.unpack_from('>I',asset,8)[0]!=22:
        raise Recast1275Error('1275 Unity SerializedFile 版本錯誤')
    meta_size,full_size,offset=struct.unpack_from('>IQQ',asset,20)
    meta_end=48+meta_size
    if (full_size!=len(asset) or asset[16]!=0 or not 48<=meta_end<=offset<=len(asset)):
        raise Recast1275Error('Unity SerializedFile Header／Metadata 邊界無效')
    r=_Reader(asset[:meta_end],48,endian='<')
    if not r.cstring().startswith('2021.3.'):
        raise Recast1275Error('非預期 Unity 版本')
    r.i32()
    if r.u8()!=1:raise Recast1275Error('Unity 物件未含預期 TypeTree')
    count=r.i32()
    if not 0<count<=5000:raise Recast1275Error('Unity ClassID 數量錯誤')
    types=[]
    for _ in range(count):
        cid=r.i32();r.u8();r.i16()
        if cid==114:r.take(16)
        r.take(16)
        nodes,strings=r.i32(),r.i32()
        if not 0<=nodes<=200000 or not 0<=strings<=4*1024*1024:
            raise Recast1275Error('Unity TypeTree 節點數量錯誤')
        r.take(nodes*32+strings)
        deps=r.i32()
        if not 0<=deps<=10000:raise Recast1275Error('Unity TypeTree 相依欄位錯誤')
        r.take(deps*4);types.append(cid)
    objects=r.i32()
    if not 0<=objects<=2_000_000:raise Recast1275Error('Unity Object 數量錯誤')
    results=[];seen=set()
    for _ in range(objects):
        r.align(4)
        path_id,position,size,type_index=r.i64(),r.i64(),r.u32(),r.i32()
        if (path_id in seen or not 0<=type_index<len(types) or position<0
                or offset+position+size>len(asset)):
            raise Recast1275Error('Unity Object 重複或位移錯誤')
        seen.add(path_id)
        results.append((path_id,types[type_index],asset[offset+position:offset+position+size]))
    return results


def mono_behaviours(asset):
    return [(path_id,blob) for path_id,cid,blob in serialized_objects(asset) if cid==114]


def parse_astar_blob(blob):
    """Only graph settings: the archived meta version is unquoted ('4.3.60')."""
    p = blob.find(b'UEsDB')
    if p < 4:
        return None
    n = struct.unpack_from('<I', blob, p-4)[0]
    if not 0 < n < 8*1024*1024 or p+n > len(blob):
        raise Recast1275Error('AstarPath ZIP Base64 長度不符')
    try:
        data = base64.b64decode(blob[p:p+n], validate=True)
        with ZipFile(io.BytesIO(data)) as inner:
            if inner.testzip() is not None:
                raise Recast1275Error('AstarPath ZIP CRC 錯誤')
            names = inner.namelist()
            if len(names) != 2 or set(names) != {'graph0.json', 'meta.json'}:
                raise Recast1275Error('AstarPath ZIP 包含未知項目或缺件')
            settings = json.loads(inner.read('graph0.json'))
            meta = inner.read('meta.json')
            # AstarPath 4.3.60 uses nonstandard "version": 4.3.60.
            meta = re.sub(rb'("version"\s*:\s*)(\d+\.\d+\.\d+)',
                          rb'\1"\2"', meta)
            meta = json.loads(meta)
    except (OSError, UnicodeError, ValueError) as exc:
        raise Recast1275Error('1275 AstarPath 設定資料解碼失敗') from exc
    if (meta.get('graphs') != 1 or
            meta.get('typeNames') != ['Pathfinding.RecastGraph'] or
            type(settings) is not dict or
            settings.get('name') != 'Recast Graph'):
        raise Recast1275Error('1275 AstarPath 圖形種類不符')
    return {'settings': settings,
            'graph_type': meta['typeNames'][0],
            'serialized_version': meta.get('version'),
            'embedded_zip_sha256': _sha(data),
            'has_serialized_walkable_mesh': False}


def load_scene_selection(archive,selection_file=None):
    """Support original 13-pair diffs and self-contained, manifest-verified single pairs."""
    with ZipFile(archive) as z:
        if selection_file is None:
            if z.namelist().count('scene_selection.json')!=1:raise Recast1275Error('來源ZIP缺少唯一的場景選取清單')
            selection=json.loads(z.read('scene_selection.json'))
        else:selection=json.loads(Path(selection_file).read_text(encoding='utf8'))
        if not isinstance(selection,dict) or selection.get('target_revision')!=1275 or not isinstance(selection.get('bundles'),list):
            raise Recast1275Error('不是1275官方場景選取清單')
        if selection.get('kind')=='current_scene_pair_1275':
            from tools.resources.collect_navigation_scene import parse_manifest,MAIN_SHA256,MANIFEST
            import zlib
            models=selection.get('model_ids')
            if (not isinstance(models,list) or len(models)!=1 or type(models[0]) is not int or not 0<models[0]<=65535
                    or selection.get('manifest_sha256_1275',{}).get('MainPackage')!=MAIN_SHA256):
                raise Recast1275Error('目前場景來源宣告無效')
            member='source/MainPackage/ManifestFiles/'+MANIFEST
            if z.namelist().count(member)!=1:raise Recast1275Error('目前場景ZIP缺少官方Manifest')
            official=parse_manifest(z.read(member))
            expected={f'mainpackage_scene_{models[0]}.bundle',f'mainpackage_scene_{models[0]}_dependency.bundle'}
            if len(selection['bundles'])!=2 or {r.get('bundle_name') for r in selection['bundles']}!=expected:
                raise Recast1275Error('目前場景主檔或相依檔不完整')
            for row in selection['bundles']:
                info=official.get(row['bundle_name'])
                if not info or any(row.get(k)!=info[k] for k in ('size','file_hash','crc')):
                    raise Recast1275Error('場景清單與官方Manifest不符')
                relative=f"MainPackage/BundleFiles/{info['file_hash'][:2]}/{info['file_hash']}/__data"
                if row.get('path')!=relative or z.namelist().count('source/'+relative)!=1:
                    raise Recast1275Error('場景ZIP路徑無效或缺件')
                blob=z.read('source/'+relative)
                if (len(blob)!=info['size'] or hashlib.md5(blob).hexdigest()!=info['file_hash']
                        or zlib.crc32(blob).to_bytes(4,'little').hex()!=info['crc'] or _sha(blob)!=row.get('sha256')):
                    raise Recast1275Error('場景本體與官方Manifest或SHA不符')
    return selection


def scene_models(selection):
    return set(selection['model_ids']) if selection.get('kind')=='current_scene_pair_1275' else {12910,*range(13216,13228)}


def extract(archive, selection_file=None):
    selection = load_scene_selection(archive,selection_file)
    if selection.get('target_revision') != 1275 or not isinstance(selection.get('bundles'), list):
        raise Recast1275Error('不是1275官方差異選取清單')
    rows = [r for r in selection['bundles']
            if r.get('group') == 'scenes' and
               re.fullmatch(r'mainpackage_scene_\d+\.bundle',
                            r.get('bundle_name', ''))]
    expected=scene_models(selection)
    if len(rows)!=len(expected) or {int(r['bundle_name'].split('_')[2].split('.')[0]) for r in rows}!=expected:
        raise Recast1275Error('1275預期的場景主Bundle不完整')
    report = []
    with ZipFile(archive) as z:
        if z.testzip() is not None:
            raise Recast1275Error('1275場景來源 ZIP CRC 無效')
        for row in rows:
            member = 'source/' + row['path']
            if z.namelist().count(member) != 1:
                raise Recast1275Error('場景來源 ZIP 缺件或重複')
            data = z.read(member)
            if len(data) != row['size'] or _sha(data) != row['sha256']:
                raise Recast1275Error('1275場景 Bundle SHA/大小不符')
            scene_objects = []
            for name, body in unity_nodes(data):
                if name.endswith('.sharedAssets'):
                    continue
                for path_id, blob in mono_behaviours(body):
                    parsed = parse_astar_blob(blob)
                    if parsed is not None:
                        scene_objects.append((path_id, parsed))
            if len(scene_objects) != 1:
                raise Recast1275Error('場景 AstarPath MonoBehaviour 不唯一')
            path_id, spec = scene_objects[0]
            report.append({
                'model_id': int(row['bundle_name'].split('_')[2].split('.')[0]),
                'bundle_sha256': row['sha256'],
                'mono_behaviour_path_id': path_id, **spec,
                'can_send_packets': False,
            })
    return {'resource_revision': 1275, 'scene_count': len(report),
            'recast_settings_verified': True,
            'navmesh_verified': False, 'can_send_packets': False,
            'scenes': report}


def main(argv=None):
    p = argparse.ArgumentParser(description='1275 官方13組場景 Recast AstarPath 唯讀解碼')
    p.add_argument('--scenes-zip', type=Path, required=True)
    p.add_argument('--select', type=Path, help='可省略以讀取ZIP內附場景清單')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(argv)
    if args.output.exists():
        raise FileExistsError('不覆寫既有分析報告')
    result = extract(args.scenes_zip, args.select)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                           encoding='utf-8')
    print(json.dumps({'resource_revision':1275,
                      'settings_extracted':len(result['scenes']),
                      'navmesh_verified':False,
                      'can_send_packets':False,
                      'output':str(args.output)},ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
