"""Known official EmojiData and exact SpriteAtlas snapshots, stored atomically."""
import base64
import hashlib
import io
from pathlib import Path
import struct
from wlre.services.parser_diagnostics import diagnosed, checkpoint

TABLES = ('EmojiData_C',)
KNOWN_SHA256 = 'b21c48d487d83463332157e1d56af0a258f26cecf2e906ca518526badcd5a75b'
ASSET = 'Assets/ResourcesBuild/Sprite/Atlas/SpriteAtlas_Emoji/SpriteAtlas_Emoji.spriteatlasv2'
MAX_BYTES = 32 * 1024 * 1024
MAX_FILES = 8


@diagnosed('emoji-known-v1')
def parse_entries(raw):
    checkpoint(offset=0, field='source_fingerprint')
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != KNOWN_SHA256:
        raise ValueError('EmojiData 未知來源指紋；保留原檔，不推測新版格式')
    if len(raw) < 4:
        raise ValueError('EmojiData 缺少筆數')
    count = struct.unpack_from('<I',raw)[0]
    if not 0 < count <= 255 or len(raw) != 4 + count * 8:
        raise ValueError('EmojiData 長度不符')
    result = {}
    for token, (ident, mark, icon, text, hidden) in enumerate(struct.iter_unpack('<BBBIB',raw[4:]),1):
        if not ident or not icon or not text or hidden not in (0,1):
            raise ValueError('EmojiData 欄位無效')
        result[str(token)] = dict(id=ident,mark_id=mark,sprite=f'Emoji_{icon:03}',
                                 text_id=text,show_in_list=not hidden,available=True)
    return result


def png_bytes(catalog, token):
    row = catalog['images'].get(str(token))
    if row is None:
        return None
    from PIL import Image
    try:
        raw = base64.b64decode(row['png'],validate=True)
        if not 0 < len(raw) <= 1024*1024 or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('表情 PNG 校驗失敗')
        with Image.open(io.BytesIO(raw)) as im:
            if im.format != 'PNG' or not (0 < im.width <= 512 and 0 < im.height <= 512):
                raise ValueError('表情圖像尺寸無效')
            if hashlib.sha256(im.convert('RGBA').tobytes()).hexdigest() != row['pixels']:
                raise ValueError('表情像素校驗失敗')
        return raw
    except (KeyError,TypeError,OSError) as error:
        raise ValueError('表情圖像資料無效') from error


def build_catalog(raw, decode):
    entries = parse_entries(raw)
    wanted = {row['sprite']+'_1' for row in entries.values()}
    images = {}
    total = 0
    for name, image in decode():
        if name not in wanted:
            continue
        if name in images or not (0 < image.width <= 512 and 0 < image.height <= 512):
            raise ValueError('表情首幀重複或尺寸無效')
        rgba=image.convert('RGBA');stream=io.BytesIO();rgba.save(stream,format='PNG')
        png=stream.getvalue();total+=len(png)
        if len(png)>1024*1024 or total>8*1024*1024:
            raise ValueError('表情圖像超出儲存額度')
        images[name]=dict(png=base64.b64encode(png).decode('ascii'),
                          sha256=hashlib.sha256(png).hexdigest(),pixels=hashlib.sha256(rgba.tobytes()).hexdigest())
    if set(images)!=wanted:
        raise ValueError('官方圖集缺少表情首幀')
    return {'entries':entries,'images':{token:images[row['sprite']+'_1'] for token,row in entries.items()}}


def import_catalog(database,key,payloads,decode,verify_sources=lambda:None):
    from wlre.storage.normalized_resources import load_parsed
    def parse():
        result=build_catalog(payloads['EmojiData_C'],decode)
        verify_sources()
        return result
    result=load_parsed(database,key,'emoji','emoji-known-sprite-v1',payloads,parse)
    if result['entries']!=parse_entries(payloads['EmojiData_C']) or set(result['images'])!=set(result['entries']):
        raise ValueError('表情資料庫索引無效')
    for token in result['entries']:
        png_bytes(result,token)
    verify_sources()
    return result


def load_verified_catalog(data_manifest,main_manifest,bundle_root,root,identity,loader):
    from wlre.services.official_incremental_sync import build_update_plan
    from wlre.services.official_bundle_download import _verified_file
    from wlre.services.world.unity_textasset import _validate_unityfs_header,extract_textasset,_find_exact_container_object
    from wlre.services.world.catalog_adapters import SourceContract
    from wlre.services.world.official_catalog_pipeline import AssetBinding
    data_asset='Assets/ResourcesBuild/Data/EmojiData_C.bytes'
    dp=build_update_plan(data_manifest,asset_paths=(data_asset,),cache_root=bundle_root)
    mp=build_update_plan(main_manifest,asset_paths=(ASSET,),cache_root=bundle_root)
    if not dp.entries or not mp.entries or len(mp.entries)>MAX_FILES or sum(e.spec.file_size for e in mp.entries)>MAX_BYTES:
        raise ValueError('表情 Bundle 計畫缺失或超出額度')
    plans=(*dp.entries,*mp.entries)
    def verify():
        if any(not _verified_file(e.spec.cache_path(bundle_root),e.spec) for e in plans):
            raise ValueError('表情 Bundle 不完整或匯入期間改變')
    verify()
    paths=tuple(e.spec.cache_path(bundle_root) for e in dp.entries)
    binding=AssetBinding(data_asset,SourceContract('scenes','EmojiData_C','stage-new-76-v1','0'*64,'DataPackage',data_manifest.spec.package_version))
    raw=extract_textasset(binding,paths,loader=loader)
    payloads={'EmojiData_C':raw}
    image_paths=[]
    for entry in mp.entries:
        path=entry.spec.cache_path(bundle_root);_validate_unityfs_header(path,path.stat().st_size)
        payloads['bundle_'+entry.spec.file_hash]=path.read_bytes();image_paths.append(path)
    def decode():
        import UnityPy
        try:
            env=UnityPy.load(*(str(p) for p in image_paths))
            obj=_find_exact_container_object(env.container,ASSET)
            if obj is None or obj.type.name!='SpriteAtlas':
                raise ValueError('官方表情 SpriteAtlas 缺失')
            atlas=obj.read()
            if not 0<len(atlas.m_PackedSprites)<=2048:
                raise ValueError('表情 Sprite 數量無效')
            wanted={r['sprite']+'_1' for r in parse_entries(raw).values()}
            for ptr in atlas.m_PackedSprites:
                sprite=ptr.read()
                if sprite.m_Name in wanted:
                    rect=sprite.m_Rect
                    if not (0<rect.width<=512 and 0<rect.height<=512):
                        raise ValueError('表情 Sprite 尺寸無效')
                    yield sprite.m_Name,sprite.image
        except Exception as error:
            raise ValueError('官方表情圖集無法完整解碼，保留原始資料') from error
    return import_catalog(Path(root)/'derived_catalogs'/'official_emoji.sqlite3',identity.key,payloads,decode,verify)


def current_catalog():
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    runtime=current_runtime()
    return getattr(runtime,'emoji_catalog',None) if runtime is not None else None


def source_token():
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    runtime=current_runtime()
    return (getattr(getattr(runtime,'catalog_identity',None),'key',None),id(getattr(runtime,'emoji_catalog',None)))


def current_entries():
    from copy import deepcopy
    catalog=current_catalog()
    return deepcopy(catalog['entries']) if catalog else {}


def current_png(token):
    catalog=current_catalog()
    return png_bytes(catalog,str(token)) if catalog else None
