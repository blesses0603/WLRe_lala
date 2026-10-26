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
    FEATURES, SourceContract, parse_feature,
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
    related_asset_paths: tuple[str, ...] = ()

    def __post_init__(self):
        paths = (self.asset_path, *self.related_asset_paths) if isinstance(
            self.related_asset_paths, tuple) else ()
        if (not isinstance(self.contract, SourceContract)
                or len(paths) < 1 or len(paths) > 16
                or any(type(path) is not str or not path or len(path) > 1024
                       or '\x00' in path or '*' in path or '?' in path
                       for path in paths)
                or len(set(paths)) != len(paths)):
            raise OfficialCatalogPipelineError('Invalid exact or related AssetPath binding')


@dataclass(frozen=True)
class ResolvedAsset:
    binding: AssetBinding
    bundle_name: str
    related_bundle_names: tuple[str, ...] = ()


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
        roots = []
        for path in (binding.asset_path, *binding.related_asset_paths):
            selected = lookup[contract.package].get(path)
            if selected is None:
                raise OfficialCatalogPipelineError('Reviewed AssetPath missing in current official Manifest')
            selectors[contract.package].add(path)
            roots.append(selected)
        resolved.append(ResolvedAsset(binding, roots[0], tuple(roots[1:])))

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
                         max_downloads=DEFAULT_MAX_DOWNLOADS, opener=None,
                         progress=None):
    """Preview, optionally sync, then parse only with a trusted extractor.

    Extractor signature: (AssetBinding, tuple[Path, ...]) -> bytes.
    Paths are cache files for the root Bundle PLUS its transitive dependencies,
    not arbitrary user-specified filesystem paths. Each is re-verified before
    the extractor sees it. Extractor must itself validate UnityFS structure and
    asset ownership; this PR does not provide a production extractor.
    """
    if not isinstance(plan, OfficialCatalogPlan):
        raise OfficialCatalogPipelineError('Expected an official catalog plan')
    if progress is not None and not callable(progress):
        raise OfficialCatalogPipelineError('Invalid Bundle progress callback')
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
    completed = 0
    total = sum(len(update.entries) for update in plan.updates)

    def on_verified_bundle(package_done, package_total, action):
        nonlocal completed
        completed += 1
        if progress is not None:
            progress(completed, total, action)

    for update in plan.updates:
        kwargs = dict(cache_root=bundle_root, download=download,
                      max_download_bytes=max_download_bytes,
                      max_downloads=max_downloads, opener=opener)
        if progress is not None and download:
            kwargs['progress'] = on_verified_bundle
        reports.append(execute_update_plan(update, **kwargs))
    summary = {**plan.summary(), 'mode': 'download' if download else 'preview',
               'updates': reports, 'parsed_features': 0}
    if extractor is None:
        return summary, {}

    paths_by_feature = verified_source_paths(plan, bundle_root=bundle_root)
    parsed = {}
    versions = {entry.name: entry.full_version for entry in plan.identity.packages}
    for source in plan.sources:
        binding = source.binding
        paths = paths_by_feature[binding.contract.feature]
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


def verified_source_paths(plan: OfficialCatalogPlan, *, bundle_root=None):
    """Resolve all roots/dependencies and recheck every official Bundle checksum.

    Caller must explicitly execute its download plan first; this function
    never downloads or extracts. Shared by reviewed and candidate pipelines.
    """
    if not isinstance(plan, OfficialCatalogPlan):
        raise OfficialCatalogPipelineError('Expected official catalog plan')
    root = (Path(bundle_root) if bundle_root is not None else
            data_root() / 'official_sync' / 'bundles')
    bundle_index = {}
    by_package = {}
    for update in plan.updates:
        by_package[update.package] = update
        for row in update.entries:
            path = row.spec.cache_path(root)
            if not _verified_file(path, row.spec):
                raise OfficialCatalogPipelineError('Verified Bundle vanished or changed')
            bundle_index[(update.package, row.spec.name)] = path
    result = {}
    for source in plan.sources:
        binding = source.binding
        update = by_package.get(binding.contract.package)
        if update is None:
            raise OfficialCatalogPipelineError('Missing planned Package')
        names = set()
        deps = {row.spec.name: row.dependencies for row in update.entries}
        def include(name):
            if name not in deps:
                raise OfficialCatalogPipelineError('Required dependency not planned')
            if name in names:
                return
            names.add(name)
            for dep in deps[name]:
                include(dep)
        for name in (source.bundle_name, *source.related_bundle_names):
            include(name)
        result[binding.contract.feature] = tuple(
            bundle_index[(binding.contract.package, name)] for name in sorted(names))
    return result
