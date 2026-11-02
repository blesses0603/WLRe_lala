"""Discover official runtime identity without trusting fixed 1275 constants.

The official .version pair and independently CRC-checked YooAsset manifests
are the source of version identity. SHA-256 is computed from verified bytes;
asset counts come from parsed manifest indexes, not hard-coded record counts.
This is diagnostic metadata only, never gameplay or packet authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from wlre.services.official_manifest_sync import (
    PACKAGES, fetch_official_manifest, spec_from_snapshot, MAX_MANIFEST_BYTES,
)
from wlre.services.official_resource_sync import (
    observe_official_versions, validate_snapshot,
)


class RuntimeIdentityError(ValueError):
    """Official runtime identity could not be verified."""


@dataclass(frozen=True)
class PackageIdentity:
    package: str
    version: str
    manifest_sha256: str
    bundle_count: int
    asset_count: int


@dataclass(frozen=True)
class RuntimeIdentity:
    data_version: str
    executable_version: str
    packages: dict[str, PackageIdentity]
    assets_ready: bool = False
    can_send_packets: bool = False


def discover_runtime_identity(*, observe=None, retrieve=None, cache_root=None):
    """Check the live version pair twice and hash verified manifests.

    Do not infer gameplay table row counts from manifest asset counts: actual
    record counts require parsing each verified TextAsset with its own schema.
    """
    observe = observe_official_versions if observe is None else observe
    retrieve = fetch_official_manifest if retrieve is None else retrieve
    try:
        before = validate_snapshot(observe())
        manifests = {}
        for package in PACKAGES:
            spec = spec_from_snapshot(before, package)
            verified = retrieve(spec, cache_root=cache_root)
            if verified.spec != spec:
                raise RuntimeIdentityError('Official Manifest version mismatch')
            with verified.cache_path.open('rb') as stream:
                raw = stream.read(MAX_MANIFEST_BYTES + 1)
            if not 0 < len(raw) <= MAX_MANIFEST_BYTES:
                raise RuntimeIdentityError('Official Manifest size invalid')
            # The receipt/hash and full parser are validated by the official
            # fetcher. Do not accept arbitrary local files as official.
            if type(verified.index) is not dict:
                raise RuntimeIdentityError('Manifest index invalid')
            bundles = verified.index.get('bundles')
            assets = verified.index.get('assets')
            if type(bundles) is not list or type(assets) is not list:
                raise RuntimeIdentityError('Manifest entries invalid')
            manifests[package] = PackageIdentity(
                package, spec.package_version, hashlib.sha256(raw).hexdigest(),
                len(bundles), len(assets))
        after = validate_snapshot(observe())
        if any(before[key] != after[key] for key in ('data_ver', 'exe_version', 'packages')):
            raise RuntimeIdentityError('Official version changed during verification')
        return RuntimeIdentity(before['data_ver'], before['exe_version'], manifests)
    except RuntimeIdentityError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeIdentityError('Official runtime identity unavailable') from exc
