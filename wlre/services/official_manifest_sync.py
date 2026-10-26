"""Read verified YooAsset manifests from the observed official PC CDN paths.

No game installation is needed. Raw manifests are retained only in the user's
local cache and never shipped in GitHub sources or releases. A full YooAsset
parser is mandatory before the bytes may be used to select Bundles.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
from urllib.request import build_opener
import zlib

from wlre.storage.paths import data_root
from wlre.resources_runtime.downloader import DownloadError, DownloadManager
from wlre.resources_runtime.downloader.https import NoRedirect as _NoRedirect
from wlre.resources_runtime.official.source import OFFICIAL_HOST, ROOT as BASE


MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_HASH_BYTES = 8
MAX_RECEIPT_BYTES = 4096
_DATA_VER = re.compile(r'[0-9]{1,4}(?:\.[0-9]{1,4}){2}\Z')
_REVISION = re.compile(r'[1-9][0-9]{0,5}_20[0-9]{2}(?:_[0-9]{2}){6}\Z')
_HASH = re.compile(r'[a-fA-F0-9]{8}\Z')
PACKAGES = ('DataPackage', 'MainPackage')


class ManifestSyncError(ValueError):
    """The official Manifest cannot be authenticated and indexed."""


@dataclass(frozen=True)
class ManifestSpec:
    data_ver: str
    package: str
    package_version: str

    def __post_init__(self):
        if (not isinstance(self.data_ver, str) or not _DATA_VER.fullmatch(self.data_ver)
                or self.package not in PACKAGES
                or not isinstance(self.package_version, str)
                or not _REVISION.fullmatch(self.package_version)):
            raise ManifestSyncError('Invalid official Manifest version or package')

    def url(self, extension):
        if extension not in ('bytes', 'hash'):
            raise ManifestSyncError('Unsupported official Manifest extension')
        return f'{BASE}/{self.data_ver}/ResourcesPC/AssetBundle/{self.package}.{extension}'

    def cache_path(self, root=None):
        base = (Path(root) if root is not None else
                data_root() / 'official_sync' / 'manifests')
        return base / self.data_ver / self.package / self.package_version / (self.package + '.bytes')

    def receipt_path(self, root=None):
        return self.cache_path(root).with_suffix('.verified.json')


def _fetch(url, *, limit, opener, timeout):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != OFFICIAL_HOST
            or parsed.port is not None or parsed.query or parsed.fragment or
            parsed.username is not None or parsed.password is not None):
        raise ManifestSyncError('Manifest URL is not the approved HTTPS source')
    try:
        with DownloadManager(opener=opener, timeout=timeout) as manager:
            return manager.read(url, limit=limit)
    except ManifestSyncError:
        raise
    except DownloadError as exc:
        if exc.args and exc.args[0] in ('unexpected_official_response', 'official_redirect_rejected'):
            raise ManifestSyncError('Manifest response location/status unexpected') from None
        raise ManifestSyncError('Official Manifest download failed') from None
    except (OSError, ValueError) as exc:
        raise ManifestSyncError('Official Manifest download failed') from exc


def _crc32_le(data):
    """YooAsset .hash uses CRC32 encoded little-endian (not %08x)."""
    return (zlib.crc32(data) & 0xffffffff).to_bytes(4, 'little').hex()


def _parse_index(data, spec, parser):
    if parser is None:
        try:
            # 正式共用解析器不再依賴工具套件，未知格式仍安全拒絕。
            from wlre.resources_runtime.parsers.yooasset import parse_manifest
        except ImportError as exc:
            raise ManifestSyncError('YooAsset runtime index parser is required') from exc
        parser = parse_manifest
    try:
        index = parser(data)
        header = index['header']
        if (header['file_version'] != '2.2.5' or
                header['package_name'] != spec.package or
                header['package_version'] != spec.package_version or
                header['output_name_style'] != 1 or
                not isinstance(index['bundles'], list) or
                not isinstance(index['assets'], list)):
            raise ManifestSyncError('Manifest identity or format differs from official .version')
        return index
    except ManifestSyncError:
        raise
    except Exception as exc:
        raise ManifestSyncError('YooAsset Manifest full index parse failed') from exc


@dataclass(frozen=True)
class VerifiedManifest:
    spec: ManifestSpec
    index: dict
    hash_text: str
    cache_path: Path
    downloaded: bool


def _atomic_write(target, body, *, prefix):
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=prefix,
                                         suffix='.partial', delete=False) as handle:
            pending = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def _receipt(spec, data, hash_text):
    return {
        'schema_version': 1,
        'data_ver': spec.data_ver,
        'package': spec.package,
        'package_version': spec.package_version,
        'manifest_url': spec.url('bytes'),
        'hash_crc32_le': hash_text,
        'sha256': hashlib.sha256(data).hexdigest(),
        'size': len(data),
    }


def read_verified_cached_manifest(spec, *, cache_root=None, parser=None):
    """Private historical Manifest, previously verified against official CDN.

    Does not make any network requests. Must NEVER replace a fresh official
    observation when deciding current-game compatibility.
    """
    if not isinstance(spec, ManifestSpec):
        raise ManifestSyncError('Manifest requires a validated spec')
    receipt_path = spec.receipt_path(cache_root)
    target = spec.cache_path(cache_root)
    try:
        with receipt_path.open('rb') as stream:
            receipt_bytes = stream.read(MAX_RECEIPT_BYTES + 1)
        if len(receipt_bytes) > MAX_RECEIPT_BYTES:
            raise ManifestSyncError('Historical Manifest receipt too large')
        receipt = json.loads(receipt_bytes.decode('utf-8'))
        if (not isinstance(receipt, dict) or set(receipt) != set(_receipt(spec, b'', '00000000'))
                or receipt['schema_version'] != 1 or type(receipt['size']) is not int
                or not 0 < receipt['size'] <= MAX_MANIFEST_BYTES
                or not isinstance(receipt['sha256'], str) or len(receipt['sha256']) != 64
                or not isinstance(receipt['hash_crc32_le'], str)
                or not _HASH.fullmatch(receipt['hash_crc32_le'])):
            raise ManifestSyncError('Historical Manifest receipt invalid')
        with target.open('rb') as stream:
            data = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(data) != receipt['size']:
            raise ManifestSyncError('Historical Manifest size mismatch')
        if receipt != _receipt(spec, data, receipt['hash_crc32_le']):
            raise ManifestSyncError('Historical Manifest digest or identity mismatch')
        if _crc32_le(data) != receipt['hash_crc32_le']:
            raise ManifestSyncError('Historical Manifest CRC32 mismatch')
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise ManifestSyncError('Historical Manifest private cache is missing or invalid') from exc
    return VerifiedManifest(spec, _parse_index(data, spec, parser),
                            receipt['hash_crc32_le'], target, False)


def fetch_official_manifest(spec, *, cache_root=None, opener=None, timeout=20, parser=None):
    """Fetch .hash + .bytes, authenticate and parse before caching.

    A remote .hash is checked on every call, including local cache hits. The
    caller must first obtain `spec.package_version` from the official .version
    response; no guessed revision or HTML directory scraping is involved.
    """
    if not isinstance(spec, ManifestSpec):
        raise ManifestSyncError('Manifest requires a validated official version spec')
    opener = build_opener(_NoRedirect()).open if opener is None else opener
    hash_body = _fetch(spec.url('hash'), limit=MAX_HASH_BYTES,
                       opener=opener, timeout=timeout)
    try:
        hash_text = hash_body.decode('ascii').lower()
    except UnicodeError as exc:
        raise ManifestSyncError('Official Manifest .hash is not ASCII hex') from exc
    if not _HASH.fullmatch(hash_text):
        raise ManifestSyncError('Official Manifest .hash is not 8 hex characters')

    destination = spec.cache_path(cache_root)
    data = None
    downloaded = False
    if destination.is_file():
        try:
            if destination.stat().st_size <= MAX_MANIFEST_BYTES:
                cached = destination.read_bytes()
                if _crc32_le(cached) == hash_text:
                    data = cached
        except OSError:
            pass  # Corrupt/inaccessible local cache is never trusted.
    if data is None:
        data = _fetch(spec.url('bytes'), limit=MAX_MANIFEST_BYTES,
                      opener=opener, timeout=timeout)
        if _crc32_le(data) != hash_text:
            raise ManifestSyncError('Official Manifest .bytes / .hash CRC32 mismatch')
        downloaded = True

    index = _parse_index(data, spec, parser)
    if downloaded:
        _atomic_write(destination, data, prefix='.manifest_')

    receipt_body = (json.dumps(_receipt(spec, data, hash_text),
                               sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')
    if len(receipt_body) > MAX_RECEIPT_BYTES:
        raise ManifestSyncError('Historical Manifest receipt exceeds safe limit')
    _atomic_write(spec.receipt_path(cache_root), receipt_body, prefix='.receipt_')

    return VerifiedManifest(spec, index, hash_text, destination, downloaded)


def spec_from_snapshot(snapshot, package):
    """Accept only fully validated official version observations."""
    from wlre.services.official_resource_sync import validate_snapshot
    validate_snapshot(snapshot)
    if package not in PACKAGES:
        raise ManifestSyncError('Unknown official package')
    return ManifestSpec(snapshot['data_ver'], package, snapshot['packages'][package])
