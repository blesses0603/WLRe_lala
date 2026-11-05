"""Versioned, bounded official Sprite -> PNG SQLite snapshots.

Raw verified Bundles stay in the official cache. Only derived PNGs may be
rebuilt; unknown sources never replace a usable snapshot.
"""
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import hashlib
import io
import json
import re
import sqlite3

MAX_IMAGES = 8192
MAX_PNG_BYTES = 4 * 1024 * 1024
MAX_TOTAL_PNG_BYTES = 96 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
MAX_DOWNLOADS = 4
PREFIX = 'Assets/ResourcesBuild/Sprite/Sprite_Item/'


def image_paths(manifest):
    paths = tuple(a['path'] for a in manifest.index['assets'] if a['path'].startswith(PREFIX))
    models = set()
    if not 0 < len(paths) <= MAX_IMAGES:
        raise ValueError('官方物品圖示清單缺少或超過上限')
    for path in paths:
        match = re.fullmatch(re.escape(PREFIX) + r's([0-9]{4,5})\.png', path)
        if not match or not 1 <= int(match[1]) <= 65535 or int(match[1]) in models:
            raise ValueError('物品圖示路徑或模型 ID 重複／無法辨識')
        models.add(int(match[1]))
    return tuple(sorted(paths))


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS image_schema (version INTEGER NOT NULL)')
    versions = db.execute('SELECT version FROM image_schema').fetchall()
    if not versions:
        db.execute('INSERT INTO image_schema VALUES (1)')
    elif versions != [(1,)]:
        raise ValueError('不支援的圖像資料庫版本')
    db.execute('CREATE TABLE IF NOT EXISTS image_versions (catalog_key TEXT PRIMARY KEY, inputs TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS map_images (catalog_key TEXT, model INTEGER, asset TEXT, '
               'png_sha TEXT, pixel_sha TEXT, png BLOB, PRIMARY KEY(catalog_key,model))')
    db.execute('CREATE TABLE IF NOT EXISTS image_history (catalog_key TEXT, model INTEGER, asset TEXT, '
               'png_sha TEXT, pixel_sha TEXT, png BLOB)')
    db.execute('CREATE TABLE IF NOT EXISTS image_attempts (catalog_key TEXT, inputs TEXT, status TEXT)')


def _decode_png(raw, png_sha, pixel_sha):
    from PIL import Image
    if (type(raw) is not bytes or not 0 < len(raw) <= MAX_PNG_BYTES
            or hashlib.sha256(raw).hexdigest() != png_sha):
        raise ValueError('物品圖示 PNG 完整性校驗失敗')
    with Image.open(io.BytesIO(raw)) as im:
        if im.format != 'PNG' or not (0 < im.width <= 512 and 0 < im.height <= 512):
            raise ValueError('物品圖示圖像格式或尺寸未經審核')
        rgba = im.convert('RGBA')
    if hashlib.sha256(rgba.tobytes()).hexdigest() != pixel_sha:
        raise ValueError('物品圖示像素校驗失敗')
    return rgba


@dataclass(frozen=True)
class ImageCatalog:
    database: Path
    catalog_key: str
    models: frozenset

    def png(self, model):
        if type(model) is not int or model not in self.models:
            return None
        try:
            with closing(sqlite3.connect(self.database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute('SELECT version FROM image_schema').fetchall() != [(1,)]:
                    raise ValueError('不支援的圖像資料庫版本')
                row = db.execute('SELECT png,png_sha,pixel_sha FROM map_images WHERE catalog_key=? AND model=?',
                                 (self.catalog_key, model)).fetchone()
        except sqlite3.Error as error:
            raise ValueError('物品圖示資料庫無法讀取') from error
        if row is None:
            raise ValueError('當次物品圖示資料庫缺少圖像')
        _decode_png(*row)
        return row[0]


def import_images(database, catalog_key, inputs, paths, decode, *, verify_sources=None):
    """Atomic import/repair; decode yields (exact asset path, PIL RGBA image)."""
    database = Path(database)
    if database.is_symlink():
        raise ValueError('圖像資料庫不可為符號連結')
    database.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(inputs, sort_keys=True, separators=(',', ':'))
    wanted = {int(path.rsplit('/', 1)[1][1:-4]): path for path in paths}
    if not 0 < len(wanted) == len(paths) <= MAX_IMAGES:
        raise ValueError('圖像索引重複或超過上限')
    with closing(sqlite3.connect(database, timeout=60)) as db:
        try:
            db.execute('BEGIN IMMEDIATE')
            _schema(db)
            previous = db.execute('SELECT inputs FROM image_versions WHERE catalog_key=?', (catalog_key,)).fetchone()
            if previous and previous[0] != encoded:
                raise ValueError('同一官方版本的圖像來源已改變')
            if previous:
                stored = db.execute('SELECT model,asset,png,png_sha,pixel_sha FROM map_images WHERE catalog_key=?', (catalog_key,)).fetchall()
                try:
                    if {r[0]:r[1] for r in stored} != wanted:
                        raise ValueError('圖像資料庫索引不完整')
                    for _,_,raw,digest,pixels in stored:
                        _decode_png(raw,digest,pixels)
                except (ValueError, OSError):
                    db.execute('INSERT INTO image_history SELECT * FROM map_images WHERE catalog_key=?', (catalog_key,))
                    db.execute('DELETE FROM map_images WHERE catalog_key=?', (catalog_key,))
                else:
                    if verify_sources is not None:
                        verify_sources()
                    db.commit()
                    return ImageCatalog(database, catalog_key, frozenset(wanted))
            seen, total = set(), 0
            for asset, image in decode():
                model = int(asset.rsplit('/', 1)[1][1:-4])
                if wanted.get(model) != asset or model in seen or not (0 < image.width <= 512 and 0 < image.height <= 512):
                    raise ValueError('解碼圖像清單、模型或尺寸不符')
                seen.add(model)
                rgba = image.convert('RGBA')
                pixels = hashlib.sha256(rgba.tobytes()).hexdigest()
                stream = io.BytesIO();rgba.save(stream, format='PNG')
                raw = stream.getvalue();total += len(raw)
                if len(raw) > MAX_PNG_BYTES or total > MAX_TOTAL_PNG_BYTES:
                    raise ValueError('物品圖示 PNG 超過儲存上限')
                digest = hashlib.sha256(raw).hexdigest()
                _decode_png(raw,digest,pixels)
                db.execute('INSERT INTO map_images VALUES (?,?,?,?,?,?)', (catalog_key,model,asset,digest,pixels,raw))
            if seen != set(wanted):
                raise ValueError('物品圖示匯入不完整')
            if verify_sources is not None:
                verify_sources()
            db.execute('INSERT OR REPLACE INTO image_versions VALUES (?,?)', (catalog_key,encoded))
            db.execute('INSERT INTO image_attempts VALUES (?,?,?)', (catalog_key,encoded,'repaired' if previous else 'imported'))
            db.commit()
        except Exception:
            db.rollback()
            # Preserve the prior transaction and record failed provenance only.
            _schema(db)
            db.execute('INSERT INTO image_attempts VALUES (?,?,?)', (catalog_key,encoded,'failed'))
            db.commit()
            raise
    return ImageCatalog(database, catalog_key, frozenset(wanted))



def load_verified_images(manifest, bundle_root, root, identity, items):
    from wlre.services.official_incremental_sync import build_update_plan
    from wlre.services.official_bundle_download import _verified_file
    from wlre.services.world.unity_textasset import _validate_unityfs_header
    paths = image_paths(manifest)
    if PREFIX+'s1000.png' not in paths:
        raise ValueError('官方物品預設圖示 s1000 缺少')
    mapping = {}
    for ident, row in items.items():
        icon = row.get('icon_id')
        if type(ident) is not int or type(icon) is not int or not 0 <= icon <= 65535:
            raise ValueError('物品圖示欄位尚未驗證')
        mapping[ident] = icon
    if not mapping:
        raise ValueError('物品圖示映射缺少')
    plan = build_update_plan(manifest, asset_paths=paths, cache_root=bundle_root)
    if not plan.entries or len(plan.entries)>MAX_DOWNLOADS or sum(e.spec.file_size for e in plan.entries)>MAX_DOWNLOAD_BYTES:
        raise ValueError('物品圖示 Bundle 計畫超出額度')
    def verify():
        if any(not _verified_file(e.spec.cache_path(bundle_root),e.spec) for e in plan.entries):
            raise ValueError('物品圖示 Bundle 不完整或匯入期間改變')
    verify()
    bundles=[];signatures={}
    for entry in plan.entries:
        path=entry.spec.cache_path(bundle_root)
        _validate_unityfs_header(path,path.stat().st_size)
        signatures[entry.spec.file_hash]=hashlib.sha256(path.read_bytes()).hexdigest()
        bundles.append(path)
    def decode():
        import UnityPy
        try:
            env=UnityPy.load(*(str(p) for p in bundles))
            by_path={}
            for asset,obj in env.container.items():
                by_path.setdefault(asset,[]).append(obj)
            for asset in paths:
                objects=by_path.get(asset,[])
                sprites=[o for o in objects if o.type.name=='Sprite']
                textures=[o for o in objects if o.type.name=='Texture2D']
                if len(objects)!=2 or len(sprites)!=1 or len(textures)!=1:
                    raise ValueError('物品 Sprite/Texture 精確路徑或數量不符')
                sprite=sprites[0].read();texture=textures[0]
                if (sprite.m_RD.texture.path_id!=texture.path_id
                        or sprite.m_RD.texture.deref().assets_file is not texture.deref().assets_file):
                    raise ValueError('物品 Sprite 並非引用同路徑 Texture')
                rect=sprite.m_Rect
                if not (0<rect.width<=512 and 0<rect.height<=512):
                    raise ValueError('物品 Sprite 尺寸超過上限')
                yield asset,sprite.image
        except Exception as error:
            raise ValueError('官方物品 Sprite 無法完整解碼；保留原檔') from error
    metadata={ident:{'width':row['item_w'],'height':row['item_h'],'open_used':row['open_used']} for ident,row in items.items()}
    inputs={'bundles':signatures,'assets':paths,'schema':1,'mapping':mapping,'metadata':metadata}
    images=import_images(Path(root)/'derived_catalogs'/'official_item_images.sqlite3',identity.key,
                         inputs,paths,decode,verify_sources=verify)
    if 1000 not in images.models:
        raise ValueError('官方物品預設圖示 s1000 缺少')
    return ItemImageCatalog(images,mapping,metadata)


@dataclass(frozen=True)
class ItemImageCatalog:
    images: ImageCatalog
    mapping: dict
    metadata: dict = None

    @property
    def catalog_key(self):
        return self.images.catalog_key

    def icon(self,item_id):
        try:ident=int(item_id)
        except (TypeError,ValueError):ident=-1
        icon=self.mapping.get(ident,1000)
        return icon if icon in self.images.models else 1000

    def png(self,item_id):
        return self.images.png(self.icon(item_id))


def current_catalog():
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    runtime=current_runtime()
    return getattr(runtime,'item_images',None) if runtime is not None else None


def source_token():
    catalog=current_catalog()
    return (getattr(catalog,'catalog_key',None),id(catalog))
