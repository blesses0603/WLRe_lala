"""Read verified YooAsset manifests from the observed official PC CDN paths.

No game installation is needed. Raw manifests are retained only in the user's
local cache and never shipped in GitHub sources or releases. A full YooAsset
parser is mandatory before the bytes may be used to select Bundles.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zlib

from wlre.storage.paths import data_root


OFFICIAL_HOST = 'wlreftp.chinesegamer.net'
BASE = 'https://' + OFFICIAL_HOST + '/WLN/TW'
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_HASH_BYTES = 8
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


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ManifestSyncError('Manifest URL redirected; origin unverified')


def _fetch(url, *, limit, opener, timeout):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != OFFICIAL_HOST
            or parsed.port is not None or parsed.query or parsed.fragment or
            parsed.username is not None or parsed.password is not None):
        raise ManifestSyncError('Manifest URL is not the approved HTTPS source')
    try:
        with opener(Request(url, headers={'User-Agent': 'WLRe-LaLa-ManifestSync/1'}),
                    timeout=timeout) as response:
            if response.geturl() != url or getattr(response, 'status', 200) != 200:
                raise ManifestSyncError('Manifest response location/status unexpected')
            declared = response.headers.get('Content-Length') if hasattr(response, 'headers') else None
            if declared is not None and (not declared.isdecimal() or int(declared) > limit):
                raise ManifestSyncError('Manifest response too large')
            body = response.read(limit + 1)
            if not body or len(body) > limit:
                raise ManifestSyncError('Manifest response empty or too large')
            if declared is not None and len(body) != int(declared):
                raise ManifestSyncError('Manifest response truncated')
            return body
    except (OSError, HTTPError, URLError) as exc:
        raise ManifestSyncError('Official Manifest download failed') from exc


def _crc32_le(data):
    """YooAsset .hash uses CRC32 encoded little-endian (not %08x)."""
    return (zlib.crc32(data) & 0xffffffff).to_bytes(4, 'little').hex()


def _parse_index(data, spec, parser):
    if parser is None:
        try:
            # Parser lives in Draft PR #53; until merged, fail closed.
            from tools.resources.lala_manifest_full_index import parse_manifest
        except ImportError as exc:
            raise ManifestSyncError('YooAsset full index parser (#53) is required') from exc
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
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.manifest_',
                                             suffix='.partial', delete=False) as handle:
                pending = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(pending, destination)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)

    return VerifiedManifest(spec, index, hash_text, destination, downloaded)


def spec_from_snapshot(snapshot, package):
    """Accept only fully validated official version observations."""
    from wlre.services.official_resource_sync import validate_snapshot
    validate_snapshot(snapshot)
    if package not in PACKAGES:
        raise ManifestSyncError('Unknown official package')
    return ManifestSpec(snapshot['data_ver'], package, snapshot['packages'][package])
