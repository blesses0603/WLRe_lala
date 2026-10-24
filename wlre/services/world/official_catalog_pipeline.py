"""Official Manifest -> exact AssetPath -> verified Bundles -> read-only adapters.

No heuristic AssetPath search, UnityFS implementation or network game commands.
The caller supplies audited AssetPath/Schema/SHA contracts, and an OPTIONAL
trusted extractor for bytes derived from the verified Bundle files. Without an
extractor the pipeline stops at a verifiable, bounded Bundle download plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from wlre.services.official_bundle_download import _verified_file
from wlre.services.official_incremental_sync import (
    DEFAULT_MAX_DOWNLOAD_BYTES, DEFAULT_MAX_DOWNLOADS,
    BundleUpdatePlan, build_update_plan, execute_update_plan,
    find_previous_verified_manifest,
)
from wlre.services.official_manifest_sync import (
    PACKAGES, VerifiedManifest, fetch_official_manifest, spec_from_snapshot,
)
from wlre.services.official_resource_sync import observe_official_versions
from wlre.services.world.catalog_adapters import (
    FEATURES, ParsedCatalog, SourceContract, parse_feature,
)
from wlre.services.world.catalog_identity import (
    OfficialCatalogIdentity, identity_from_verified_manifests,
)
from wlre.storage.paths import data_root


class OfficialCatalogPipelineError(ValueError):
    """Unsafe/unreviewed catalog source or incomplete verified Bundle."""


@dataclass(frozen=True)
class AssetBinding:
    """Explicitly reviewed mapping: a feature's decoded bytes come from an AssetPath."""

    asset_path: str
    contract: SourceContract

    def __post_init__(self):
        if (not isinstance(self.asset_path, str) or not self.asset_path
                or len(self.asset_path) > 1024 or '\x00' in self.asset_path
                or '*' in self.asset_path or '?' in self.asset_path
                or not isinstance(self.contract, SourceContract)):
            raise OfficialCatalogPipelineError('Invalid exact AssetPath/source binding')


@dataclass(frozen=True)
class ResolvedAsset:
    binding: AssetBinding
    bundle_name: str


@dataclass(frozen=True)
class OfficialCatalogPlan:
    identity: OfficialCatalogIdentity
    sources: tuple[ResolvedAsset, ...]
    updates: tuple[BundleUpdatePlan, ...]

    @property
    def catalog_key(self):
        return self.identity.key

    def summary(self):
        return {
            'catalog_key': self.catalog_key,
            'data_ver': self.identity.data_ver,
            'source_count': len(self.sources),
            'features': list(FEATURES),
            'packages': [update.summary() for update in self.updates],
            'needs_extractor': True,
            'can_send_packets': False,
            'assets_ready': False,
        }


def _validate_manifest_index(manifest):
    if not isinstance(manifest, VerifiedManifest):
        raise OfficialCatalogPipelineError('Official verified Manifest is required')
    index = manifest.index
    if not isinstance(index, dict) or not isinstance(index.get('assets'), list):
        raise OfficialCatalogPipelineError('Manifest Asset table absent')
    assets = {}
    for row in index['assets']:
        if (not isinstance(row, dict) or not isinstance(row.get('path'), str)
                or not isinstance(row.get('bundle_name'), str)
                or not row['path'] or not row['bundle_name']
                or row['path'] in assets):
            raise OfficialCatalogPipelineError('Manifest contains ambiguous AssetPath')
        assets[row['path']] = row['bundle_name']
    return assets


def plan_catalog_pipeline(snapshot, manifests: Mapping[str, VerifiedManifest],
                          bindings, *, previous_manifests=None, bundle_root=None):
    """Verify both manifests, then locate EXACT assets and dependency closure.

    Nothing is downloaded by this function. Identity is derived by re-reading
    both officially verified cached manifest bytes and checking their CRC.
    """
    identity = identity_from_verified_manifests(snapshot, manifests)
    if (not isinstance(bindings, (tuple, list)) or len(bindings) != len(FEATURES)
            or any(not isinstance(item, AssetBinding) for item in bindings)
            or {item.contract.feature for item in bindings} != set(FEATURES)):
        raise OfficialCatalogPipelineError('Exactly one reviewed binding per feature is required')
    if previous_manifests is not None and (
            not isinstance(previous_manifests, Mapping)
            or any(key not in PACKAGES for key in previous_manifests)):
        raise OfficialCatalogPipelineError('Invalid previous Manifest package set')

    versions = {entry.name: entry.full_version for entry in identity.packages}
    lookup = {package: _validate_manifest_index(manifests[package])
              for package in PACKAGES}
    selectors = {package: set() for package in PACKAGES}
    resolved = []
    for binding in bindings:
        contract = binding.contract
        if versions.get(contract.package) != contract.package_version:
            raise OfficialCatalogPipelineError('Source revision differs from official Manifest')
        selected = lookup[contract.package].get(binding.asset_path)
        if selected is None:
            raise OfficialCatalogPipelineError('Reviewed AssetPath missing in current official Manifest')
        selectors[contract.package].add(binding.asset_path)
        resolved.append(ResolvedAsset(binding, selected))

    updates = []
    for package in PACKAGES:
        if not selectors[package]:
            continue
        previous = (None if previous_manifests is None else
                    previous_manifests.get(package))
        updates.append(build_update_plan(
            manifests[package], asset_paths=sorted(selectors[package]),
            previous=previous, cache_root=bundle_root))
    return OfficialCatalogPlan(identity, tuple(resolved), tuple(updates))


def plan_current_catalog(bindings, *, observe=None, retrieve=None,
                         previous_finder=None, manifest_root=None, bundle_root=None):
    """Fetch fresh official metadata + BOTH .hash/.bytes; fail closed offline."""
    observe = observe_official_versions if observe is None else observe
    retrieve = fetch_official_manifest if retrieve is None else retrieve
    previous_finder = (find_previous_verified_manifest if previous_finder is None
                       else previous_finder)
    snapshot = observe()
    manifests = {}
    history = {}
    for package in PACKAGES:
        spec = spec_from_snapshot(snapshot, package)
        current = retrieve(spec, cache_root=manifest_root)
        manifests[package] = current
        history[package] = previous_finder(current, cache_root=manifest_root)
    return plan_catalog_pipeline(snapshot, manifests, bindings,
                                 previous_manifests=history, bundle_root=bundle_root)


def run_catalog_pipeline(plan: OfficialCatalogPlan, *, download=False,
                         extractor: Callable | None = None, bundle_root=None,
                         max_download_bytes=DEFAULT_MAX_DOWNLOAD_BYTES,
                         max_downloads=DEFAULT_MAX_DOWNLOADS, opener=None):
    """Preview, optionally sync, then parse only with a trusted extractor.

    Extractor signature: (AssetBinding, tuple[Path, ...]) -> bytes.
    Paths are cache files for the root Bundle PLUS its transitive dependencies,
    not arbitrary user-specified filesystem paths. Each is re-verified before
    the extractor sees it. Extractor must itself validate UnityFS structure and
    asset ownership; this PR does not provide a production extractor.
    """
    if not isinstance(plan, OfficialCatalogPlan):
        raise OfficialCatalogPipelineError('Expected an official catalog plan')
    if extractor is not None and (not callable(extractor) or not download):
        raise OfficialCatalogPipelineError('Extraction requires explicit sync and trusted extractor')
    if (type(max_download_bytes) is not int or max_download_bytes < 0
            or type(max_downloads) is not int or max_downloads < 0):
        raise OfficialCatalogPipelineError('Invalid download limits')
    if download and (
            sum(x.download_bytes for x in plan.updates) > max_download_bytes
            or sum(x.download_count for x in plan.updates) > max_downloads):
        raise OfficialCatalogPipelineError('Aggregate download quota exceeded')

    reports = []
    for update in plan.updates:
        reports.append(execute_update_plan(
            update, cache_root=bundle_root, download=download,
            max_download_bytes=max_download_bytes, max_downloads=max_downloads,
            opener=opener))
    summary = {**plan.summary(), 'mode': 'download' if download else 'preview',
               'updates': reports, 'parsed_features': 0}
    if extractor is None:
        return summary, {}

    root = (Path(bundle_root) if bundle_root is not None else
            data_root() / 'official_sync' / 'bundles')
    bundle_index = {}
    for update in plan.updates:
        by_name = {row.spec.name: row for row in update.entries}
        for row in update.entries:
            path = row.spec.cache_path(root)
            if not _verified_file(path, row.spec):
                raise OfficialCatalogPipelineError('Verified Bundle vanished or changed')
            bundle_index[(update.package, row.spec.name)] = path

    parsed = {}
    versions = {entry.name: entry.full_version for entry in plan.identity.packages}
    for source in plan.sources:
        binding = source.binding
        update = next((p for p in plan.updates
                       if p.package == binding.contract.package), None)
        if update is None:
            raise OfficialCatalogPipelineError('Missing planned Package')
        names = {source.bundle_name}
        dependency_map = {row.spec.name: row.dependencies for row in update.entries}
        def include(name):
            if name not in dependency_map:
                raise OfficialCatalogPipelineError('Required dependency not planned')
            for dependency in dependency_map[name]:
                if dependency not in names:
                    names.add(dependency)
                    include(dependency)
        include(source.bundle_name)
        paths = tuple(bundle_index[(binding.contract.package, name)]
                      for name in sorted(names))
        try:
            raw = extractor(binding, paths)
            parsed[binding.contract.feature] = parse_feature(
                catalog_key=plan.catalog_key, package_versions=versions,
                contract=binding.contract, raw=raw)
        except OfficialCatalogPipelineError:
            raise
        except Exception as exc:
            raise OfficialCatalogPipelineError('Extracted source validation failed; no catalog activated') from exc
    if set(parsed) != set(FEATURES):
        raise OfficialCatalogPipelineError('Incomplete derived Catalog')
    summary['parsed_features'] = len(parsed)
    summary['needs_extractor'] = False
    # Parsing success never proves live protocol, navigation or login compatibility.
    return summary, parsed
