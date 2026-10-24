"""Version-agnostic identity for future official NPC/shop/craft/scene catalogs.

It identifies *source revisions*, not completed extraction or compatibility.
Never treats an officially observed version as LaLa-supported by itself.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import zlib

from wlre.services.official_manifest_sync import (
    MAX_MANIFEST_BYTES, PACKAGES, VerifiedManifest,
)
from wlre.services.official_resource_sync import validate_snapshot
from wlre.storage.paths import data_root


CATALOG_SCHEMA_VERSION = 1
REQUIRED_FEATURES = ('npc', 'shops', 'crafting', 'scenes')


class CatalogIdentityError(ValueError):
    """Official catalog inputs lack sufficient verified provenance."""


@dataclass(frozen=True)
class PackageRevision:
    name: str
    full_version: str
    manifest_sha256: str
    manifest_crc32_le: str


@dataclass(frozen=True)
class OfficialCatalogIdentity:
    """Complete revision key, including independent Package timestamps/hashes."""

    data_ver: str
    exe_version: str
    packages: tuple[PackageRevision, PackageRevision]
    schema_version: int = CATALOG_SCHEMA_VERSION

    def as_dict(self):
        return {
            'schema_version': self.schema_version,
            'data_ver': self.data_ver,
            'exe_version': self.exe_version,
            'packages': [{
                'name': item.name,
                'full_version': item.full_version,
                'manifest_sha256': item.manifest_sha256,
                'manifest_crc32_le': item.manifest_crc32_le,
            } for item in self.packages],
        }

    @property
    def key(self):
        content = json.dumps(self.as_dict(), ensure_ascii=True, sort_keys=True,
                             separators=(',', ':')).encode('ascii')
        return hashlib.sha256(content).hexdigest()

    def private_catalog_dir(self, root=None):
        base = (Path(root) if root is not None else
                data_root() / 'official_sync' / 'derived_catalogs')
        return base / self.key


def identity_from_verified_manifests(snapshot, manifests):
    """Compute exact update identity from both officially authenticated indexes.

    The caller must obtain these manifests via official_manifest_sync and its
    full parser. This function rechecks private bytes before deriving identity.
    It does NOT mark NPC/shop/crafting/scene extraction as complete or ready.
    """
    validate_snapshot(snapshot)
    if not isinstance(manifests, dict) or set(manifests) != set(PACKAGES):
        raise CatalogIdentityError('Both official Package manifests are required')
    revisions = []
    for name in PACKAGES:
        manifest = manifests[name]
        if (not isinstance(manifest, VerifiedManifest) or
                manifest.spec.package != name or
                manifest.spec.data_ver != snapshot['data_ver'] or
                manifest.spec.package_version != snapshot['packages'][name]):
            raise CatalogIdentityError('Official snapshot/Manifest identity mismatch')
        header = manifest.index.get('header', {})
        if (header.get('package_name') != name or
                header.get('package_version') != manifest.spec.package_version or
                header.get('file_version') != '2.2.5'):
            raise CatalogIdentityError('YooAsset parser header identity mismatch')
        try:
            with manifest.cache_path.open('rb') as handle:
                data = handle.read(MAX_MANIFEST_BYTES + 1)
        except OSError as exc:
            raise CatalogIdentityError('Verified private Manifest is unreadable') from exc
        if not 0 < len(data) <= MAX_MANIFEST_BYTES:
            raise CatalogIdentityError('Private Manifest size is not trustworthy')
        crc = (zlib.crc32(data) & 0xffffffff).to_bytes(4, 'little').hex()
        if crc != manifest.hash_text:
            raise CatalogIdentityError('Private Manifest CRC differs from official verification')
        revisions.append(PackageRevision(name, manifest.spec.package_version,
                                         hashlib.sha256(data).hexdigest(), crc))
    return OfficialCatalogIdentity(snapshot['data_ver'], snapshot['exe_version'],
                                   tuple(revisions))
