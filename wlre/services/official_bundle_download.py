"""Verified on-demand YooAsset Bundle download primitive (not activated by UI).

Never guesses manifests or downloads entire packages. Only call this with a
bundle record from a separately verified official Manifest. The remote Manifest
URLs are now confirmed; this service still is not wired into startup or login.
"""

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.request import build_opener

from wlre.storage.paths import data_root
from wlre.resources_runtime.downloader import DownloadManager, FileIntegrity
from wlre.resources_runtime.downloader.https import NoRedirect as _NoRedirect
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
    identity = FileIntegrity(spec.file_size, spec.file_hash, spec.file_crc)
    with DownloadManager() as manager:
        return manager.verify_file(path, identity)


def fetch_bundle(spec, *, cache_root=None, opener=None, timeout=20,
                 cancel_event=None, progress=None, segments=1):
    """共用下載器核對大小、MD5、CRC 後原子快取；保留舊 Path API。"""
    if not isinstance(spec, BundleSpec):
        raise BundleDownloadError('Bundle requires validated Manifest metadata')
    opener = build_opener(_NoRedirect()).open if opener is None else opener
    manager = DownloadManager(opener=opener, timeout=timeout)
    identity = FileIntegrity(spec.file_size, spec.file_hash, spec.file_crc)
    try:
        return manager.download(spec.url, identity, spec.cache_path(cache_root),
                                cancel_event=cancel_event, progress=progress, segments=segments)
    except InterruptedError:
        raise
    except (OSError, ValueError) as exc:
        raise BundleDownloadError('Official Bundle download or verification failed') from exc
    finally:
        manager.close()
