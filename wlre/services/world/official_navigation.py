"""Pinned official 1275 navigation snapshots in private per-user storage.

The client uses official caches for offline geometry inspection. This installer
does not promote startup snapshots to verified live navigation.
"""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

from wlre.paths import RESOURCE_ROOT
from wlre.storage.paths import data_root
from wlre.services.world.official_cache_format import CacheError, decode_cache

ARCHIVE = '1275_OfficialNavigation.zip'


def fingerprints():
    return json.loads((RESOURCE_ROOT / 'official_navigation_1275.json').read_text(encoding='utf8'))['models']


def default_path():
    return data_root() / 'official_resources_1275' / ARCHIVE


def _validate_archive(raw):
    if len(raw) > 32 * 1024 * 1024:
        raise CacheError('官方導航封裝超過大小限制')
    pins = fingerprints()
    expected = {'manifest.json'} | {f'official/{model}.zip' for model in pins}
    with ZipFile(BytesIO(raw)) as z:
        if len(z.namelist()) != len(expected) or set(z.namelist()) != expected:
            raise CacheError('官方導航封裝缺件、重複或含未知檔案')
        if sum(i.file_size for i in z.infolist()) > 32 * 1024 * 1024:
            raise CacheError('官方導航封裝展開大小超限')
        manifest = json.loads(z.read('manifest.json'))
        if manifest != {'resource_revision': 1275, 'kind': 'official_astar_startup_caches',
                        'models': sorted(pins, key=int)}:
            raise CacheError('官方導航封裝版本或模型清單不符')
        decoded = {}
        for model, pin in pins.items():
            blob = z.read(f'official/{model}.zip')
            if len(blob) != pin['cache_bytes'] or hashlib.sha256(blob).hexdigest() != pin['cache_sha256']:
                raise CacheError('官方導航快取指紋不符：' + model)
            result = decode_cache(blob)
            if len(result['mesh']['tiles'][0]['triangles']) != pin['faces']:
                raise CacheError('官方導航面數不符：' + model)
            result['source'] = {'resource_revision': 1275, 'model_id': model,
                                'kind': 'official_astar_startup_cache', **pin}
            decoded[model] = result
    return decoded


def validate_archive(raw):
    try:
        return _validate_archive(raw)
    except (BadZipFile, EOFError) as exc:
        raise CacheError('官方導航封裝損壞或不是有效 ZIP') from exc


def load_archive(path=None):
    path = Path(path) if path is not None else default_path()
    if path.stat().st_size > 32 * 1024 * 1024:
        raise CacheError('官方導航封裝超過大小限制')
    return validate_archive(path.read_bytes())


def install(archive, *, destination=None):
    """Validate all models before an exclusive, atomic publish."""
    source = Path(archive)
    decoded = load_archive(source)
    blob = source.read_bytes()
    # Validate the bytes being published, including a concurrently replaced input.
    validate_archive(blob)
    target = Path(destination) if destination is not None else default_path()
    if target.exists():
        raise FileExistsError('官方導航資料已存在，安裝器不覆寫：' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.navigation-', delete=False) as stream:
            staging = Path(stream.name)
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging, target)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)
    return {'models': len(decoded), 'path': str(target), 'can_send_packets': False}


def package(source_dirs, output):
    """Package exact pinned raw caches; derived candidate JSON is never accepted."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    blobs = {}
    pins = fingerprints()
    for model, pin in pins.items():
        matches = [Path(root) / f'{model}_official_cache.zip' for root in source_dirs
                   if (Path(root) / f'{model}_official_cache.zip').is_file()]
        if len(matches) != 1:
            raise CacheError('每個官方模型需要唯一來源快取：' + model)
        blob = matches[0].read_bytes()
        if len(blob) != pin['cache_bytes'] or hashlib.sha256(blob).hexdigest() != pin['cache_sha256']:
            raise CacheError('官方來源快取指紋不符：' + model)
        blobs[model] = blob
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps({'resource_revision': 1275,
            'kind': 'official_astar_startup_caches', 'models': sorted(pins, key=int)}))
        for model in sorted(pins, key=int):
            z.writestr(f'official/{model}.zip', blobs[model])
    raw = buffer.getvalue()
    validate_archive(raw)
    with output.open('xb') as stream:
        stream.write(raw)
    return output
