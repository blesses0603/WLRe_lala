"""Verified on-demand YooAsset Bundle download primitive (not activated by UI).

Never guesses manifests or downloads entire packages. Only call this with a
bundle record from a separately verified official Manifest. The remote Manifest
URLs are now confirmed; this service still is not wired into startup or login.
"""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zlib

from wlre.storage.paths import data_root
from wlre.resources_runtime.official.source import OFFICIAL_HOST as OFFICIAL_BUNDLE_HOST, ROOT as BASE


MAX_BUNDLE_BYTES = 256 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,190}\.bundle\Z')
_DATA_VER = re.compile(r'[0-9]{1,4}(?:\.[0-9]{1,4}){2}\Z')
_REVISION = re.compile(r'[1-9][0-9]{0,5}_20[0-9]{2}(?:_[0-9]{2}){6}\Z')
_HEX32 = re.compile(r'[a-fA-F0-9]{32}\Z')
_HEX8 = re.compile(r'[a-fA-F0-9]{8}\Z')


class BundleDownloadError(ValueError):
    pass


@dataclass(frozen=True)
class BundleSpec:
    """Manifest-derived immutable file identity; not an arbitrary URL."""

    data_ver: str
    package: str
    package_version: str
    name: str
    file_size: int
    file_hash: str
    file_crc: str

    def __post_init__(self):
        if (not _DATA_VER.fullmatch(self.data_ver) or
                self.package not in ('DataPackage', 'MainPackage') or
                not _REVISION.fullmatch(self.package_version) or
                not _NAME.fullmatch(self.name) or
                type(self.file_size) is not int or not 0 < self.file_size <= MAX_BUNDLE_BYTES or
                not _HEX32.fullmatch(self.file_hash) or not _HEX8.fullmatch(self.file_crc)):
            raise BundleDownloadError('Manifest Bundle metadata invalid or unsupported')

    @property
    def url(self):
        return (BASE + '/' + self.data_ver + '/ResourcesPC/AssetBundle/' + self.name)

    def cache_path(self, root=None):
        base = Path(root) if root is not None else data_root() / 'official_sync' / 'bundles'
        return base / self.package / self.package_version / self.file_hash.lower() / self.name


def spec_from_manifest(*, data_ver, package, index, name):
    """Select a single entry; caller must authenticate full Manifest first."""
    header = index.get('header') if isinstance(index, dict) else None
    if (not isinstance(header, dict) or header.get('package_name') != package or
            header.get('file_version') != '2.2.5' or
            header.get('output_name_style') != 1):
        raise BundleDownloadError('Unsupported or mismatched YooAsset Manifest')
    bundles = index.get('bundles')
    if not isinstance(bundles, list):
        raise BundleDownloadError('Manifest Bundle table missing')
    rows = [entry for entry in bundles if isinstance(entry, dict) and entry.get('name') == name]
    if len(rows) != 1:
        raise BundleDownloadError('Bundle not uniquely present in verified Manifest')
    row = rows[0]
    try:
        return BundleSpec(data_ver, package, header['package_version'], row['name'],
                          row['file_size'], row['file_hash'], row['file_crc'])
    except (TypeError, KeyError) as exc:
        raise BundleDownloadError('Manifest Bundle record incomplete') from exc


def _verified_file(path, spec):
    if not path.is_file() or path.stat().st_size != spec.file_size:
        return False
    md5 = hashlib.md5(usedforsecurity=False)
    crc = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b''):
            md5.update(chunk)
            crc = zlib.crc32(chunk, crc)
    return (md5.hexdigest() == spec.file_hash.lower() and
            (crc & 0xffffffff).to_bytes(4, 'little').hex() == spec.file_crc.lower())


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BundleDownloadError('Bundle URL redirected; source has not been verified')


def fetch_bundle(spec, *, cache_root=None, opener=None, timeout=20):
    """GET one pinned official bundle, verify size+MD5+CRC, atomically cache.

    No parallelism, retries, automatic package scanning or deletion. Offline
    tests inject an opener; the default opener rejects every redirect.
    """
    if not isinstance(spec, BundleSpec):
        raise BundleDownloadError('Bundle requires validated Manifest metadata')
    url = spec.url
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != OFFICIAL_BUNDLE_HOST:
        raise BundleDownloadError('Source is not the approved official CDN')
    destination = spec.cache_path(cache_root)
    if _verified_file(destination, spec):
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    opener = build_opener(_NoRedirect()).open if opener is None else opener
    pending = None
    try:
        with opener(Request(url, headers={'User-Agent': 'WLRe-LaLa-OfficialSync/1'}),
                    timeout=timeout) as response:
            if response.geturl() != url or getattr(response, 'status', 200) != 200:
                raise BundleDownloadError('Unexpected remote Bundle response')
            declared = response.headers.get('Content-Length') if hasattr(response, 'headers') else None
            if declared is not None and (not declared.isdecimal() or int(declared) != spec.file_size):
                raise BundleDownloadError('Official Bundle response size differs from Manifest')
            md5 = hashlib.md5(usedforsecurity=False)
            crc = 0
            length = 0
            with tempfile.NamedTemporaryFile(dir=destination.parent,
                                             prefix='.bundle_', suffix='.partial',
                                             delete=False) as handle:
                pending = Path(handle.name)
                while True:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    length += len(chunk)
                    if length > spec.file_size:
                        raise BundleDownloadError('Downloaded Bundle exceeds declared size')
                    md5.update(chunk)
                    crc = zlib.crc32(chunk, crc)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        # YooAsset FileCRC is CRC32 encoded in *little-endian byte order*.
        # The usual f'{crc:08x}' reverses that order and rejects valid Bundles.
        if (length != spec.file_size or md5.hexdigest() != spec.file_hash.lower() or
                (crc & 0xffffffff).to_bytes(4, 'little').hex() != spec.file_crc.lower()):
            raise BundleDownloadError('Official Bundle size/hash/CRC verification failed')
        os.replace(pending, destination)
        return destination
    except (OSError, HTTPError, URLError) as exc:
        raise BundleDownloadError('Official Bundle download failed') from exc
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
