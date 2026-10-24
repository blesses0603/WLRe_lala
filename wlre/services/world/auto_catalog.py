"""Zero-config official Catalog candidate discovery for LaLa (read-only).

No user-supplied bindings.json, pinned-hash guessing or runtime activation.
Official Manifest determines EXACT, reviewed logical AssetPaths; a newly
observed revision gets a private candidate with digest receipts, never an
automatically approved gameplay/catalog revision.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

from wlre.services.official_manifest_sync import (
    PACKAGES, fetch_official_manifest, spec_from_snapshot,
)
from wlre.services.official_incremental_sync import (
    DEFAULT_MAX_DOWNLOAD_BYTES, DEFAULT_MAX_DOWNLOADS,
    find_previous_verified_manifest,
)
from wlre.services.official_resource_sync import observe_official_versions
from wlre.services.world.catalog_adapters import (
    FEATURES, MAX_SOURCE_BYTES, SourceContract, parse_feature,
)
from wlre.services.world.official_catalog_pipeline import (
    AssetBinding, OfficialCatalogPipelineError,
    plan_catalog_pipeline, run_catalog_pipeline, verified_source_paths,
)
from wlre.storage.paths import data_root


class AutoCatalogError(ValueError):
    """Auto-discovery is incomplete or official revision is not yet supported."""


# Exact reviewed logical paths. Do not fuzzy-search game assets by filename;
# a moved/renamed asset requires new developer review before parsing.
_ASSET_ROOT = 'Assets/ResourcesBuild/Data/'
_SOURCE_MAP = {
    'npc': ('Eve.bytes', 'EventData.NewNpc', 'eve-npc-json-v1', ()),
    'shops': ('Eve.bytes', 'EventData.NewInteract', 'eve-interact-json-v1',
              ('ItemData_C.bytes',)),
    'crafting': ('SmithData_C.bytes', 'SmithData_C', 'smith-new-33-v1', ()),
    'scenes': ('ScenesData_C.bytes', 'ScenesData_C', 'stage-new-76-v1', ()),
}
# This is a *planning-only* placeholder, never used to accept data.
_PENDING_DIGEST = '0' * 64
MAX_CANDIDATE_BYTES = 4 * MAX_SOURCE_BYTES + 1024 * 1024


def _bindings_for_snapshot(snapshot):
    package = 'DataPackage'
    revision = snapshot['packages'][package]
    return tuple(
        AssetBinding(_ASSET_ROOT + _SOURCE_MAP[feature][0],
                     SourceContract(feature, _SOURCE_MAP[feature][1],
                                    _SOURCE_MAP[feature][2], _PENDING_DIGEST,
                                    package, revision),
                     tuple(_ASSET_ROOT + name for name in _SOURCE_MAP[feature][3]))
        for feature in FEATURES
    )


def _candidate_path(identity, candidate_root=None):
    root = (Path(candidate_root) if candidate_root is not None else
            data_root() / 'official_sync' / 'derived_catalogs')
    return identity.private_catalog_dir(root) / 'candidate.zip'


def _trusted_cached_candidate(path, key):
    """Self-check private candidate ZIP. Does not confer release approval."""
    if not path.is_file() or path.stat().st_size > MAX_CANDIDATE_BYTES:
        return None
    try:
        with zipfile.ZipFile(path) as z:
            expected = {'candidate.json'} | {f'{f}.source' for f in FEATURES}
            if set(z.namelist()) != expected:
                return None
            meta = json.loads(z.read('candidate.json'))
            if (type(meta) is not dict or meta.get('schema_version') != 1
                    or meta.get('catalog_key') != key
                    or meta.get('status') != 'review_required'
                    or meta.get('assets_ready') is not False
                    or meta.get('can_send_packets') is not False
                    or meta.get('approved') is not False
                    or set(meta.get('features', {})) != set(FEATURES)):
                return None
            for feature in FEATURES:
                desc = meta['features'][feature]
                if (type(desc) is not dict or
                        type(desc.get('bytes')) is not int or
                        not 0 < desc['bytes'] <= MAX_SOURCE_BYTES or
                        type(desc.get('sha256')) is not str):
                    return None
                raw = z.read(feature + '.source')
                if len(raw) != desc['bytes'] or hashlib.sha256(raw).hexdigest() != desc['sha256']:
                    return None
            return meta
    except (OSError, zipfile.BadZipFile, ValueError, TypeError, KeyError):
        return None


def _store_candidate(identity, bytes_by_feature, parsed, *, candidate_root=None):
    path = _candidate_path(identity, candidate_root)
    features = {}
    for feature in FEATURES:
        raw = bytes_by_feature[feature]
        cat = parsed[feature]
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_BYTES:
            raise AutoCatalogError('Derived source invalid or too large')
        features[feature] = {
            'schema_id': cat.schema_id,
            'package': 'DataPackage',
            'package_version': next(
                p.full_version for p in identity.packages if p.name == 'DataPackage'),
            'asset_path': _ASSET_ROOT + _SOURCE_MAP[feature][0],
            'related_asset_paths': [_ASSET_ROOT + x for x in _SOURCE_MAP[feature][3]],
            'source_name': cat.source_name,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'bytes': len(raw), 'record_count': cat.record_count,
        }
    metadata = {
        'schema_version': 1, 'catalog_key': identity.key,
        'official_identity': identity.as_dict(), 'features': features,
        'status': 'review_required', 'approved': False,
        'assets_ready': False, 'can_send_packets': False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.catalog_',
                                         suffix='.partial', delete=False) as fd:
            pending = Path(fd.name)
            with zipfile.ZipFile(fd, 'w', compression=zipfile.ZIP_DEFLATED) as z:
                for feature in FEATURES:
                    z.writestr(feature + '.source', bytes_by_feature[feature])
                z.writestr('candidate.json', json.dumps(
                    metadata, ensure_ascii=False, sort_keys=True,
                    separators=(',', ':')).encode('utf-8'))
            fd.flush()
            os.fsync(fd.fileno())
        if _trusted_cached_candidate(pending, identity.key) is None:
            raise AutoCatalogError('Private candidate ZIP integrity check failed')
        os.replace(pending, path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return metadata


def run_auto_catalog(*, download=True, parse=True, observe=None, retrieve=None,
                     previous_finder=None, extractor=None,
                     manifest_root=None, bundle_root=None, candidate_root=None,
                     max_download_bytes=DEFAULT_MAX_DOWNLOAD_BYTES,
                     max_downloads=DEFAULT_MAX_DOWNLOADS, opener=None):
    """One bounded background iteration; no UI objects, network commands or login.

    parse=True is only allowed with download=True; both default on for LaLa's
    auto-prepare worker. Call download=False,parse=False for a safe preview.
    """
    if parse and not download:
        raise AutoCatalogError('Cannot parse before explicit verified Bundle sync')
    if (type(max_download_bytes) is not int or max_download_bytes < 0
            or type(max_downloads) is not int or max_downloads < 0):
        raise AutoCatalogError('Invalid automatic download limits')
    observe = observe_official_versions if observe is None else observe
    retrieve = fetch_official_manifest if retrieve is None else retrieve
    previous_finder = (find_previous_verified_manifest if previous_finder is None
                       else previous_finder)
    snapshot = observe()
    manifests, previous = {}, {}
    for package in PACKAGES:
        current = retrieve(spec_from_snapshot(snapshot, package),
                           cache_root=manifest_root)
        manifests[package] = current
        previous[package] = previous_finder(current, cache_root=manifest_root)
    bindings = _bindings_for_snapshot(snapshot)
    plan = plan_catalog_pipeline(snapshot, manifests, bindings,
                                 previous_manifests=previous, bundle_root=bundle_root)
    result = {
        'catalog_key': plan.catalog_key, 'data_ver': plan.identity.data_ver,
        'features': list(FEATURES),
        'status': 'preview', 'approved': False,
        'assets_ready': False, 'can_send_packets': False,
        'downloads_required': sum(p.download_count for p in plan.updates),
        'download_bytes': sum(p.download_bytes for p in plan.updates),
    }
    # Previous candidate files are content-checked, but never change the
    # official version/login gate. Fresh official manifest is still mandatory.
    cached = _trusted_cached_candidate(_candidate_path(plan.identity, candidate_root),
                                       plan.catalog_key)
    if cached is not None and download and parse:
        return {**result, 'status': 'review_required',
                'cache': 'verified_private_candidate',
                'record_counts': {f: cached['features'][f]['record_count'] for f in FEATURES}}
    if not download:
        return result
    if parse and extractor is None:
        try:
            import UnityPy
            if not callable(UnityPy.load):
                raise ImportError('UnityPy.load missing')
        except ImportError as exc:
            raise AutoCatalogError('LaLa 尚未內建 UnityPy，無法解包官方資源') from exc
        from wlre.services.world.catalog_source_extractor import extract_catalog_source
        extractor = extract_catalog_source
    if extractor is not None and not callable(extractor):
        raise AutoCatalogError('Invalid extractor')
    # Quotas checked for BOTH packages in run_catalog_pipeline, prior to writes.
    sync, _ = run_catalog_pipeline(
        plan, download=True, extractor=None, bundle_root=bundle_root,
        max_download_bytes=max_download_bytes, max_downloads=max_downloads,
        opener=opener)
    result['verified_bundles'] = sum(len(p.entries) for p in plan.updates)
    if not parse:
        return {**result, 'status': 'downloaded_unparsed'}
    paths = verified_source_paths(plan, bundle_root=bundle_root)
    raw_by_feature, parsed = {}, {}
    revisions = {p.name: p.full_version for p in plan.identity.packages}
    # All source digests computed AFTER official MD5/CRC checks. Self-computed
    # SHA does not constitute independent release approval.
    for source in plan.sources:
        provisional = source.binding
        feature = provisional.contract.feature
        try:
            raw = extractor(provisional, paths[feature])
            if type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_BYTES:
                raise AutoCatalogError('Extractor returned invalid source bytes')
            digest = hashlib.sha256(raw).hexdigest()
            contract = SourceContract(
                feature, provisional.contract.source_name,
                provisional.contract.schema_id, digest,
                provisional.contract.package, provisional.contract.package_version)
            parsed[feature] = parse_feature(catalog_key=plan.catalog_key,
                                            package_versions=revisions,
                                            contract=contract, raw=raw)
            raw_by_feature[feature] = raw
        except Exception as exc:
            raise AutoCatalogError(
                f'{feature} 新版資料解析失敗；未儲存或啟用任何候選目錄') from exc
    if set(parsed) != set(FEATURES):
        raise AutoCatalogError('Official source candidate is incomplete')
    metadata = _store_candidate(plan.identity, raw_by_feature, parsed,
                                candidate_root=candidate_root)
    return {**result, 'status': 'review_required', 'cache': 'new_private_candidate',
            'record_counts': {f: metadata['features'][f]['record_count']
                              for f in FEATURES}}
