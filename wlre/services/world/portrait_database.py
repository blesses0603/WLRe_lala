"""Atomic private portrait snapshots from the reviewed official data projection."""
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import hashlib
import io
import json
import sqlite3

from wlre.services.world.portrait_mapping import CHARACTERS, parse_npc_portraits

MAX_IMAGES = 1024
MAX_PNG = 512 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_SIDE = 256


def _encode(image):
    if not 0 < image.width <= MAX_SIDE or not 0 < image.height <= MAX_SIDE:
        raise ValueError('官方頭像尺寸超出驗證範圍')
    rgba = image.convert('RGBA')
    stream = io.BytesIO()
    rgba.save(stream, format='PNG')
    raw = stream.getvalue()
    if len(raw) > MAX_PNG:
        raise ValueError('官方頭像大小超過上限')
    return raw, hashlib.sha256(raw).hexdigest(), hashlib.sha256(rgba.tobytes()).hexdigest()


def _decode(raw, digest, pixels):
    from PIL import Image
    if not 0 < len(raw) <= MAX_PNG or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('官方頭像快取校驗失敗')
    with Image.open(io.BytesIO(raw)) as image:
        if image.format != 'PNG' or not 0 < image.width <= MAX_SIDE or not 0 < image.height <= MAX_SIDE:
            raise ValueError('官方頭像快取尺寸不符')
        result = image.convert('RGBA')
    if hashlib.sha256(result.tobytes()).hexdigest() != pixels:
        raise ValueError('官方頭像像素校驗失敗')
    return result


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS portrait_schema(version INTEGER NOT NULL)')
    versions = db.execute('SELECT version FROM portrait_schema').fetchall()
    if not versions:
        db.execute('INSERT INTO portrait_schema VALUES(1)')
    elif versions != [(1,)]:
        raise ValueError('官方頭像資料庫版本不支援')
    db.execute('CREATE TABLE IF NOT EXISTS portrait_versions(key TEXT PRIMARY KEY, inputs TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS portraits(key TEXT, kind TEXT, icon TEXT, '
               'base BLOB, base_sha TEXT, base_pixels TEXT, mask BLOB, mask_sha TEXT, mask_pixels TEXT, '
               'metadata TEXT, metadata_sha TEXT, PRIMARY KEY(key,kind,icon))')


@dataclass(frozen=True)
class PortraitCatalog:
    database: Path
    catalog_key: str
    characters: dict
    npcs: dict
    available: frozenset

    def image(self, kind, icon, palettes):
        if (kind, icon) not in self.available:
            return None
        with closing(sqlite3.connect(self.database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            if db.execute('SELECT version FROM portrait_schema').fetchall() != [(1,)]:
                raise ValueError('官方頭像資料庫版本不符')
            row = db.execute('SELECT base,base_sha,base_pixels,mask,mask_sha,mask_pixels,metadata,metadata_sha '
                             'FROM portraits WHERE key=? AND kind=? AND icon=?',
                             (self.catalog_key, kind, icon)).fetchone()
        if row is None:
            return None
        if type(row[6]) is not str or hashlib.sha256(row[6].encode()).hexdigest() != row[7]:
            raise ValueError('官方頭像材質快取校驗失敗')
        from wlre.services.world.portrait_render import render
        base = _decode(*row[:3])
        try:
            mask = _decode(*row[3:6])
            try:
                return render(base, mask, dict(palettes), json.loads(row[6]))
            finally:
                mask.close()
        finally:
            base.close()


def import_portraits(database, key, inputs, decode, npcs, *, verify_sources):
    """Decode into one transaction; keep previous versions on every failure."""
    database = Path(database)
    if database.is_symlink():
        raise ValueError('頭像資料庫不可為符號連結')
    database.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(inputs, sort_keys=True, separators=(',', ':'))
    expected = frozenset(tuple(pair) for pair in inputs.get('expected', ()))
    if not expected or not 0 < len(expected) <= MAX_IMAGES:
        raise ValueError('官方頭像來源索引缺少')
    with closing(sqlite3.connect(database, timeout=60)) as db:
        try:
            db.execute('BEGIN IMMEDIATE')
            _schema(db)
            previous = db.execute('SELECT inputs FROM portrait_versions WHERE key=?', (key,)).fetchone()
            if previous and previous[0] != encoded:
                raise ValueError('同版頭像來源已改變')
            if previous:
                stored = db.execute('SELECT kind,icon,base,base_sha,base_pixels,mask,mask_sha,mask_pixels,metadata,metadata_sha '
                                    'FROM portraits WHERE key=?', (key,)).fetchall()
                try:
                    if {(row[0], row[1]) for row in stored} != expected:
                        raise ValueError('頭像資料庫不完整')
                    for row in stored:
                        _decode(*row[2:5]).close(); _decode(*row[5:8]).close()
                        if type(row[8]) is not str or hashlib.sha256(row[8].encode()).hexdigest() != row[9] or not isinstance(json.loads(row[8]), dict):
                            raise ValueError('頭像材質資料不符')
                except (ValueError, OSError, TypeError):
                    pass  # Rebuild only from the verified same-version inputs.
                else:
                    verify_sources()
                    db.commit()
                    return PortraitCatalog(database, key, dict(CHARACTERS), npcs,
                                           frozenset((r[0], r[1]) for r in stored))
            db.execute('DELETE FROM portraits WHERE key=?', (key,))
            seen, total = set(), 0
            for kind, icon, base, mask, metadata in decode():
                ident = (kind, icon)
                if kind not in ('player', 'companion') or type(icon) is not str or not icon or ident in seen:
                    raise ValueError('官方頭像識別重複或不符')
                seen.add(ident)
                if len(seen) > MAX_IMAGES:
                    raise ValueError('官方頭像數目超出上限')
                try:
                    b, m = _encode(base), _encode(mask)
                finally:
                    base.close(); mask.close()
                total += len(b[0]) + len(m[0])
                if total > MAX_TOTAL:
                    raise ValueError('官方頭像快取超出上限')
                meta = json.dumps(metadata, sort_keys=True, separators=(',', ':'))
                if len(meta) > 32768:
                    raise ValueError('官方頭像材質資料超出上限')
                db.execute('INSERT INTO portraits VALUES(?,?,?,?,?,?,?,?,?,?,?)', (key,kind,icon,*b,*m,meta,hashlib.sha256(meta.encode()).hexdigest()))
            if seen != expected:
                raise ValueError('官方頭像匯入不完整')
            verify_sources()
            db.execute('INSERT OR REPLACE INTO portrait_versions VALUES(?,?)', (key, encoded))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return PortraitCatalog(database, key, dict(CHARACTERS), npcs, frozenset(seen))


def load_verified_portraits(manifest, bundle_root, root, identity, npc_raw):
    from wlre.services.world.portrait_assets import source_specs, extract_portraits, BUNDLES
    from wlre.services.world.portrait_mapping import DATA_VERSION
    from wlre.services.official_bundle_download import _verified_file
    versions = {p.name:p.full_version for p in identity.packages}
    if identity.data_ver != '1.3.23' or versions.get('DataPackage') != DATA_VERSION:
        raise ValueError('頭像對應資料版本尚未驗證')
    npcs = parse_npc_portraits(npc_raw)
    specs = source_specs(manifest)
    decode, inputs = extract_portraits(manifest, bundle_root)
    inputs['npc_sha256'] = hashlib.sha256(npc_raw).hexdigest()
    def verify():
        for spec in specs:
            path = spec.cache_path(bundle_root)
            if (not _verified_file(path, spec) or path.is_symlink()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != BUNDLES[spec.name]):
                raise ValueError('官方頭像來源在匯入期間改變')
    return import_portraits(Path(root)/'derived_catalogs'/'official_portraits.sqlite3',
                            identity.key, inputs, decode, npcs, verify_sources=verify)
