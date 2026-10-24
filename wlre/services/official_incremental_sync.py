"""Plan required Bundle dependency closure and opt-in incremental downloads.

Inputs must be fully authenticated YooAsset Manifest indexes. This component
does not guess which assets LaLa's NPC/shop/crafting/scene parsers require;
each caller supplies exact, release-reviewed selectors. No blanket download.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile

from wlre.services.official_bundle_download import (
    BundleDownloadError, BundleSpec, MAX_BUNDLE_BYTES, _verified_file,
    fetch_bundle, spec_from_manifest,
)
from wlre.services.official_manifest_sync import (
    ManifestSpec, ManifestSyncError, VerifiedManifest, read_verified_cached_manifest,
)
from wlre.storage.paths import data_root


DEFAULT_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_DOWNLOADS = 32
MAX_HISTORICAL_RECEIPTS = 4096


class IncrementalSyncError(ValueError):
    """A release's needed assets cannot be safely planned or fetched."""


@dataclass(frozen=True)
class PlannedBundle:
    spec: BundleSpec
    action: str  # 'cached', 'reuse_previous', 'download'
    change: str  # 'added', 'modified', 'unchanged', 'first_baseline'
    reuse_from: BundleSpec | None
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class BundleUpdatePlan:
    data_ver: str
    package: str
    package_version: str
    previous_version: str | None
    requested_assets: tuple[str, ...]
    requested_bundles: tuple[str, ...]
    entries: tuple[PlannedBundle, ...]
    added_count: int
    modified_count: int
    removed_count: int

    @property
    def download_bytes(self):
        return sum(row.spec.file_size for row in self.entries if row.action == 'download')

    @property
    def download_count(self):
        return sum(row.action == 'download' for row in self.entries)

    def summary(self):
        """No game AssetPath or raw Bundle data in this summary."""
        return {
            'data_ver': self.data_ver,
            'package': self.package,
            'package_version': self.package_version,
            'previous_version': self.previous_version,
            'required_asset_count': len(self.requested_assets),
            'required_bundle_count': len(self.entries),
            'cached_count': sum(row.action == 'cached' for row in self.entries),
            'reuse_previous_count': sum(row.action == 'reuse_previous' for row in self.entries),
            'download_count': self.download_count,
            'download_bytes': self.download_bytes,
            'manifest_added_bundles': self.added_count,
            'manifest_modified_bundles': self.modified_count,
            'manifest_removed_bundles': self.removed_count,
            'assets_ready': False,
        }


def _bundle_root(root):
    return Path(root) if root is not None else data_root() / 'official_sync' / 'bundles'


def find_previous_verified_manifest(current, *, cache_root=None, max_candidates=64):
    """Find newest older *verified private receipt*, without contacting CDN.

    This is a prior observation for differential planning, NOT proof that
    the older game resources were installed or supported by the runtime.
    """
    if not isinstance(current, VerifiedManifest):
        raise IncrementalSyncError('Current official Manifest must be verified')
    base = (Path(cache_root) if cache_root is not None else
            data_root() / 'official_sync' / 'manifests')

    def version_key(value):
        return tuple(int(part) for part in value.split('_'))

    if (type(max_candidates) is not int or not 1 <= max_candidates <= 256):
        raise IncrementalSyncError('Invalid historical Manifest comparison limit')
    candidates = []
    scanned = 0
    for receipt in base.glob(f'*/{current.spec.package}/*/{current.spec.package}.verified.json'):
        scanned += 1
        if scanned > MAX_HISTORICAL_RECEIPTS:
            raise IncrementalSyncError('Historical Manifest directory exceeds safe scan bound')
        try:
            spec = ManifestSpec(receipt.parents[2].name, current.spec.package,
                                receipt.parent.name)
        except (ManifestSyncError, ValueError):
            continue
        if version_key(spec.package_version) < version_key(current.spec.package_version):
            candidates.append(spec)
    # A healthy long-lived installation accumulates many versions. Select
    # the newest bounded set before opening any historical receipts; do not
    # block official updates just because there are over 64 older versions.
    candidates.sort(key=lambda spec: version_key(spec.package_version), reverse=True)
    for spec in candidates[:max_candidates]:
        try:
            return read_verified_cached_manifest(spec, cache_root=base)
        except ManifestSyncError:
            continue  # Unverified history cannot be used as a diff baseline.
    return None


def _manifest_records(verified):
    if not isinstance(verified, VerifiedManifest):
        raise IncrementalSyncError('Only a verified official Manifest is accepted')
    index, spec = verified.index, verified.spec
    if (not isinstance(index, dict) or not isinstance(index.get('header'), dict)
            or index['header'].get('package_name') != spec.package
            or index['header'].get('package_version') != spec.package_version
            or index['header'].get('file_version') != '2.2.5'
            or index['header'].get('output_name_style') != 1):
        raise IncrementalSyncError('Verified Manifest identity is inconsistent')
    try:
        names = {row['name']: row for row in index['bundles']}
        if len(names) != len(index['bundles']):
            raise IncrementalSyncError('Duplicate Bundle names')
        for row in names.values():
            if any(dep not in names for dep in row['dependencies']):
                raise IncrementalSyncError('Missing Bundle dependency')
        assets = {row['path']: row['bundle_name'] for row in index['assets']}
        if len(assets) != len(index['assets']):
            raise IncrementalSyncError('Duplicate Asset paths')
    except (KeyError, TypeError) as exc:
        raise IncrementalSyncError('Incomplete YooAsset index') from exc
    return names, assets


def build_update_plan(current, *, asset_paths=(), bundle_names=(), previous=None,
                      cache_root=None):
    """Resolve chosen asset/bundle roots plus all transitive dependencies.

    Compares the *entire* old/new Bundle index by stable name/fingerprint but
    only schedules selected roots. A renamed Bundle with identical FileHash can
    reuse a verified previous file without downloading the same bytes.
    """
    names, assets = _manifest_records(current)
    requested_assets = tuple(sorted(set(asset_paths)))
    requested_bundles = tuple(sorted(set(bundle_names)))
    if not requested_assets and not requested_bundles:
        raise IncrementalSyncError('Explicit required assets or Bundles are mandatory')
    for name in (*requested_assets, *requested_bundles):
        if not isinstance(name, str) or not name or len(name) > 1024 or '\x00' in name:
            raise IncrementalSyncError('Invalid required asset/Bundle selector')
    missing_assets = sorted(set(requested_assets) - assets.keys())
    missing_bundles = sorted(set(requested_bundles) - names.keys())
    if missing_assets or missing_bundles:
        raise IncrementalSyncError(
            f'Required resources missing from current Manifest: '
            f'{len(missing_assets)} assets, {len(missing_bundles)} Bundles')

    old_names = {}
    old_spec = None
    old_content_specs = {}
    if previous is not None:
        old_names, _ = _manifest_records(previous)
        old_spec = previous.spec
        if old_spec.package != current.spec.package:
            raise IncrementalSyncError('Cannot diff different YooAsset packages')
        for old in old_names.values():
            try:
                old_bundle = spec_from_manifest(data_ver=old_spec.data_ver,
                                                package=old_spec.package,
                                                index=previous.index, name=old['name'])
            except BundleDownloadError:
                continue  # An oversized or unsupported historical file cannot be reused.
            key = (old_bundle.file_size, old_bundle.file_hash.lower(), old_bundle.file_crc.lower())
            old_content_specs.setdefault(key, []).append(old_bundle)

    roots = set(requested_bundles) | {assets[path] for path in requested_assets}
    ordered = []
    visiting, visited = set(), set()

    def visit(name):
        if name in visiting:
            raise IncrementalSyncError('YooAsset dependency cycle')
        if name in visited:
            return
        visiting.add(name)
        for dep in sorted(names[name]['dependencies']):
            visit(dep)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in sorted(roots):
        visit(name)

    from tools.resources.lala_manifest_full_index import bundle_fingerprint
    added = set(names) - set(old_names) if previous is not None else set()
    removed = set(old_names) - set(names) if previous is not None else set()
    modified = ({name for name in names.keys() & old_names.keys()
                 if bundle_fingerprint(names[name]) != bundle_fingerprint(old_names[name])}
                if previous is not None else set())

    base = _bundle_root(cache_root)
    entries = []
    for name in ordered:
        try:
            spec = spec_from_manifest(data_ver=current.spec.data_ver,
                                      package=current.spec.package,
                                      index=current.index, name=name)
        except BundleDownloadError as exc:
            raise IncrementalSyncError('Required Bundle is invalid or exceeds safe size') from exc
        action, reuse_from = 'download', None
        if _verified_file(spec.cache_path(base), spec):
            action = 'cached'
        else:
            key = (spec.file_size, spec.file_hash.lower(), spec.file_crc.lower())
            for candidate in old_content_specs.get(key, []):
                if _verified_file(candidate.cache_path(base), candidate):
                    action, reuse_from = 'reuse_previous', candidate
                    break
        change = ('first_baseline' if previous is None else
                  'added' if name in added else 'modified' if name in modified else 'unchanged')
        entries.append(PlannedBundle(spec, action, change, reuse_from,
                                     tuple(names[name]['dependencies'])))
    return BundleUpdatePlan(current.spec.data_ver, current.spec.package,
                            current.spec.package_version,
                            old_spec.package_version if old_spec is not None else None,
                            requested_assets, requested_bundles, tuple(entries),
                            len(added), len(modified), len(removed))


def _reuse_verified_bundle(row, base):
    """Hard-link verified private old bytes into new version, atomically.

    Cross-filesystem volumes fall back to a bounded copy. No game file is
    changed in-place and incomplete destination files are never accepted.
    """
    source_spec, destination_spec = row.reuse_from, row.spec
    if source_spec is None or not _verified_file(source_spec.cache_path(base), source_spec):
        raise IncrementalSyncError('Previous cached Bundle is unavailable')
    destination = destination_spec.cache_path(base)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.bundle_reuse_',
                                         suffix='.partial', delete=False) as handle:
            pending = Path(handle.name)
        pending.unlink()
        try:
            os.link(source_spec.cache_path(base), pending)
        except OSError:
            shutil.copyfile(source_spec.cache_path(base), pending)
        if not _verified_file(pending, destination_spec):
            raise IncrementalSyncError('Reused Bundle failed checksum verification')
        os.replace(pending, destination)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return destination


def execute_update_plan(plan, *, cache_root=None, download=False,
                        max_download_bytes=DEFAULT_MAX_DOWNLOAD_BYTES,
                        max_downloads=DEFAULT_MAX_DOWNLOADS, opener=None, timeout=20,
                        progress=None):
    """Perform an explicit bounded run; preview is the default.

    Does not automatically mark runtime assets ready. If any required file is
    missing after an error, callers must preserve their existing login gate.
    """
    if not isinstance(plan, BundleUpdatePlan):
        raise IncrementalSyncError('A verified Bundle update plan is required')
    if progress is not None and not callable(progress):
        raise IncrementalSyncError('Invalid Bundle completion callback')
    if not download:
        return {**plan.summary(), 'mode': 'preview', 'completed': 0}
    if (type(max_download_bytes) is not int or max_download_bytes < 0 or
            type(max_downloads) is not int or max_downloads < 0):
        raise IncrementalSyncError('Invalid incremental download quota')
    # Preflight BEFORE a single network request or local hard-link.
    if plan.download_bytes > max_download_bytes or plan.download_count > max_downloads:
        raise IncrementalSyncError('Planned downloads exceed the explicit byte/file quota')
    base = _bundle_root(cache_root)
    completed = 0
    try:
        for row in plan.entries:
            if row.action == 'cached':
                if not _verified_file(row.spec.cache_path(base), row.spec):
                    raise IncrementalSyncError('Bundle cache changed since planning')
            elif row.action == 'reuse_previous':
                _reuse_verified_bundle(row, base)
            elif row.action == 'download':
                fetch_bundle(row.spec, cache_root=base, opener=opener, timeout=timeout)
            else:
                raise IncrementalSyncError('Unknown Bundle action')
            completed += 1
            # Call only after official size/MD5/CRC verification or validated
            # reuse; this count must never mean 'bytes requested'.
            if progress is not None:
                progress(completed, len(plan.entries), row.action)
    except (OSError, BundleDownloadError) as exc:
        raise IncrementalSyncError('Incremental Bundle sync interrupted; not ready') from exc
    return {**plan.summary(), 'mode': 'download', 'completed': completed,
            'verified_required_bundles': len(plan.entries),
            'assets_ready': False}
