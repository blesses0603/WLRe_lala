"""Read one exact UnityFS TextAsset from verified private Bundle cache files.

UnityPy handles UnityFS compression and SerializedFile type layouts; this
module applies LaLa's bounded, exact-AssetPath, no-guessing safety contract.
Unreviewed Eve event-index transformation is intentionally NOT attempted.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import struct
from typing import Callable

from wlre.services.world.catalog_adapters import MAX_SOURCE_BYTES
from wlre.services.world.official_catalog_pipeline import AssetBinding

MAX_INPUT_BUNDLES = 24
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 128 * 1024 * 1024
MAX_BLOCK_INFO_BYTES = 4 * 1024 * 1024
MAX_CONTAINER_ENTRIES = 100_000


class UnityTextAssetError(ValueError):
    """Unknown/ambiguous UnityFS, path, class or decoded TextAsset bytes."""


def _loader(path):
    try:
        import UnityPy
    except ImportError as exc:
        raise UnityTextAssetError(
            'UnityFS 解包需要另行安裝 UnityPy：python -m pip install "UnityPy>=1.23,<2"') from exc
    return UnityPy.load(str(path))


def _validate_unityfs_header(path, size):
    """Check basic UnityFS layout before passing data to the bounded decoder."""
    with path.open('rb') as stream:
        if stream.read(8) != b'UnityFS\x00':
            raise UnityTextAssetError('Unsupported non-UnityFS Bundle')
        version_bytes = stream.read(4)
        if len(version_bytes) != 4 or struct.unpack('>I', version_bytes)[0] not in (6, 7, 8):
            raise UnityTextAssetError('Unsupported UnityFS header format version')
        for _ in range(2):
            name = bytearray()
            for _ in range(128):
                char = stream.read(1)
                if not char:
                    raise UnityTextAssetError('Truncated UnityFS version header')
                if char == b'\x00':
                    break
                name.extend(char)
            else:
                raise UnityTextAssetError('Unbounded UnityFS version header')
            if not name:
                raise UnityTextAssetError('Missing UnityFS engine version')
        tail = stream.read(20)
        if len(tail) != 20:
            raise UnityTextAssetError('Truncated UnityFS block header')
        total, packed, unpacked, flags = struct.unpack('>QIII', tail)
        if (total != size or not 0 < packed <= MAX_BLOCK_INFO_BYTES
                or not 0 < unpacked <= MAX_BLOCK_INFO_BYTES
                or packed > size - stream.tell()
                or flags & 0x3f not in (0, 1, 2, 3)
                or flags & ~0x3ff):
            raise UnityTextAssetError('Unexpected UnityFS block sizes or encrypted flags')


def _payload(obj, asset_path):
    if getattr(getattr(obj, 'type', None), 'name', None) != 'TextAsset':
        raise UnityTextAssetError('Manifest AssetPath does not resolve to a TextAsset')
    try:
        data = obj.read() if callable(getattr(obj, 'read', None)) else obj.parse_as_object()
    except Exception as exc:
        raise UnityTextAssetError('Unity SerializedFile TextAsset decoding failed') from exc
    name = getattr(data, 'name', None)
    if name is None:
        name = getattr(data, 'm_Name', None)
    filename = PurePosixPath(asset_path).name
    expected_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
    if type(name) is not str or name not in (expected_name, filename):
        raise UnityTextAssetError('TextAsset identity differs from reviewed AssetPath')
    script = getattr(data, 'script', None)
    if script is None:
        script = getattr(data, 'm_Script', None)
    if type(script) is bytes:
        body = script
    elif type(script) is str:
        # UnityPy legacy maps arbitrary .bytes via surrogateescape.
        body = script.encode('utf-8', 'surrogateescape')
    else:
        raise UnityTextAssetError('TextAsset has no supported binary script payload')
    if not 0 < len(body) <= MAX_SOURCE_BYTES:
        raise UnityTextAssetError('Empty or oversized decoded TextAsset')
    return body



def _find_exact_container_object(container, asset_path):
    """Resolve exact AssetPath via UnityPy 1.25's ContainerHelper.items().

    Environment.container no longer guarantees a dict. ContainerHelper.items
    can preserve duplicate keys whereas its compatibility dict cannot. Never
    search by filename or relax full, verified Manifest AssetPath matching.
    """
    if not callable(getattr(container, 'items', None)):
        raise UnityTextAssetError('Unity container AssetPath index unavailable')
    try:
        entries = container.items()
        found = None
        for index, pair in enumerate(entries):
            if index >= MAX_CONTAINER_ENTRIES:
                raise UnityTextAssetError('Unity container index exceeds safe entry limit')
            try:
                path, obj = pair
            except (TypeError, ValueError) as exc:
                raise UnityTextAssetError('Malformed Unity container AssetPath entry') from exc
            if type(path) is not str:
                raise UnityTextAssetError('Malformed Unity container AssetPath key')
            if path == asset_path:
                if found is not None:
                    raise UnityTextAssetError('Duplicate TextAsset AssetPath in one Unity container')
                found = obj
        return found
    except UnityTextAssetError:
        raise
    except Exception as exc:
        raise UnityTextAssetError('Unity container AssetPath enumeration failed') from exc


def extract_textasset(binding: AssetBinding, bundle_paths: tuple[Path, ...], *,
                      loader: Callable | None = None) -> bytes:
    """Unpack exact .bytes TextAsset bytes through UnityPy's .container.items().

    Input paths MUST come from the verified official pipeline; the pipeline
    verifies bundle MD5, CRC and length immediately before this call. Loading
    independent bundles avoids accidental environment container key overwrite.
    Duplicate matching AssetPaths across dependencies fail closed.

    A verified extracted Eve TextAsset is raw Eve binary, *not* a ready-made
    EventData.NewNpc/NewInteract JSON index. Schema/digest checks in
    parse_feature prevent accepting it as either index.
    """
    if (not isinstance(binding, AssetBinding)
            or type(bundle_paths) is not tuple
            or not 1 <= len(bundle_paths) <= MAX_INPUT_BUNDLES):
        raise UnityTextAssetError('Expected a reviewed binding and bounded Bundle paths')
    if loader is not None and not callable(loader):
        raise UnityTextAssetError('Invalid UnityFS loader')
    candidates = []
    total = 0
    seen = set()
    for candidate in bundle_paths:
        if not isinstance(candidate, Path):
            raise UnityTextAssetError('Non-path Bundle source')
        path = candidate.resolve(strict=True)
        if path in seen:
            raise UnityTextAssetError('Duplicated Bundle source')
        seen.add(path)
        size = path.stat().st_size
        if not 0 < size <= MAX_BUNDLE_BYTES:
            raise UnityTextAssetError('Bundle exceeds safe extraction size limit')
        total += size
        if total > MAX_TOTAL_INPUT_BYTES:
            raise UnityTextAssetError('Combined Bundle size exceeds safe limit')
        _validate_unityfs_header(path, size)
        candidates.append(path)

    read_bundle = _loader if loader is None else loader
    result = None
    for path in candidates:
        try:
            env = read_bundle(path)
            obj = _find_exact_container_object(env.container, binding.asset_path)
        except UnityTextAssetError:
            raise
        except Exception as exc:
            raise UnityTextAssetError('UnityFS decompression or container decoding failed') from exc
        if obj is None:
            continue
        if result is not None:
            raise UnityTextAssetError('Duplicate TextAsset AssetPath in supplied Bundles')
        result = _payload(obj, binding.asset_path)
    if result is None:
        raise UnityTextAssetError('Exact AssetPath is missing from verified UnityFS Bundles')
    return result
