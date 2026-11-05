"""Official Manifest resource verification and SQLite metadata synchronization.

No downloaded source or SQLite metadata grants gameplay/network permission.
No candidate ZIP is created or promoted by this synchronization entry point.
"""
from __future__ import annotations

from wlre.services.parser_diagnostics import update_diagnostics, record_identity

import hashlib
from pathlib import Path

from wlre.services.official_manifest_sync import (
    PACKAGES, fetch_official_manifest, spec_from_snapshot,
)
from wlre.services.official_incremental_sync import (
    DEFAULT_MAX_DOWNLOAD_BYTES, DEFAULT_MAX_DOWNLOADS,
    find_previous_verified_manifest,
)
from wlre.services.official_resource_sync import observe_official_versions
from wlre.services.world.catalog_adapters import (
    CatalogAdapterError, FEATURES, MAX_SOURCE_BYTES, SourceContract, parse_feature,
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
    'items': ('ItemData_C.bytes', 'ItemData_C', 'itemdata-v1', ()),
    'npc': ('Eve.bytes', 'EventData.NewNpc', 'eve-npc-json-v1', ()),
    'shops': ('Eve.bytes', 'EventData.NewInteract', 'eve-interact-json-v1',
              ('ItemData_C.bytes',)),
    'crafting': ('SmithData_C.bytes', 'SmithData_C', 'smith-reviewed-v1', ()),
    'scenes': ('ScenesData_C.bytes', 'ScenesData_C', 'stage-new-76-v1', ()),
}
# This is a *planning-only* placeholder, never used to accept data.
_PENDING_DIGEST = '0' * 64


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


def _refresh_existing_classification(identity, manifests, candidate_root, progress):
    """Best-effort, read-only classification of both official Asset lists.

    Index files remain private metadata and do not authorize runtime access.
    Run both before optional downloads and after raw inventory updates, so
    previously present and newly collected entries share one lookup table.
    """
    try:
        from wlre.services.world.resource_classification import (
            write_verified_classification)
        summary = write_verified_classification(
            identity, manifests, candidate_root=candidate_root)
    except Exception:
        # Classification is optional and must not change the prior login gate
        # or erase a successfully validated four-feature candidate.
        if progress is not None:
            progress('classification_unavailable', {})
        return {'status': 'pending_error', 'approved': False,
                'assets_ready': False, 'can_send_packets': False}
    if progress is not None:
        progress('classification_ready', {
            'total': summary['asset_total'],
            'existing': summary['locally_indexed']})
    return {**summary, 'status': 'indexed_metadata_only'}


def _rebuild_known_resources(result, *, identity, manifests, bundle_root,
                             candidate_root, max_download_bytes,
                             max_downloads, opener, progress):
    """Continue collecting missing official DataPackage assets in bounded batches.

    No manual ZIP insertion or restart is required for a partial first batch.
    Every pass checks the same official manifest, bundle hashes and the
    catalog-key-isolated inventory. A parser error never authorizes gameplay.
    """
    from wlre.services.world.resource_rebuilder import (
        rebuild_raw_resources, MAX_PER_LAUNCH_BYTES, MAX_PER_LAUNCH_DOWNLOADS)
    from wlre.services.official_bundle_download import fetch_bundle

    def bounded_fetch(spec, *, cache_root):
        return fetch_bundle(spec, cache_root=cache_root,
                            opener=opener, timeout=8)

    remaining_bytes = max(0, max_download_bytes - result['download_bytes'])
    remaining_files = max(0, max_downloads - result['downloads_required'])
    total_downloaded = 0
    summary = None
    if progress is not None:
        progress('raw_rebuild', {})
    try:
        # Cap the total work by the ordinary official Launcher session budget
        # and by eight batches, irrespective of how many resources are missing.
        for _ in range(8):
            batch_files = min(MAX_PER_LAUNCH_DOWNLOADS, remaining_files)
            batch_bytes = min(MAX_PER_LAUNCH_BYTES, remaining_bytes)
            current = rebuild_raw_resources(
                identity, manifests['DataPackage'], bundle_root=bundle_root,
                candidate_root=candidate_root, max_downloads=batch_files,
                max_download_bytes=batch_bytes, fetcher=bounded_fetch,
                progress=progress)
            summary = current
            changed = current.get('new_bundle_downloads', 0)
            if (type(changed) is not int or changed < 0
                    or changed > batch_files):
                raise AutoCatalogError('Invalid raw resource download accounting')
            total_downloaded += changed
            attempts = current.get('download_attempts', changed)
            if type(attempts) is not int or not changed <= attempts <= batch_files:
                raise AutoCatalogError('Invalid raw resource attempt accounting')
            remaining_files -= attempts
            # Use the actual independently verified downloaded bytes.
            charged = current.get('attempted_download_bytes',
                                  current.get('new_bundle_download_bytes',
                                              batch_bytes if changed else 0))
            if (type(charged) is not int or charged < 0
                    or charged > batch_bytes or (changed and not charged)):
                raise AutoCatalogError('Invalid raw resource byte accounting')
            remaining_bytes -= charged
            if (current['complete_raw_assets'] or not changed
                    or remaining_files == 0 or remaining_bytes <= 0):
                break
    except Exception:
        if progress is not None:
            progress('raw_rebuild_unavailable', {})
        return {'status': 'pending_error', 'formal_approved': False,
                'assets_ready': False, 'can_send_packets': False}
    if progress is not None:
        progress('raw_rebuild_ready', {
            'completed': summary['asset_collected'],
            'total': summary['asset_total'],
            'formal_blockers': summary.get('formal_blockers')})
    return {**summary, 'new_bundle_downloads': total_downloaded,
            'status': ('complete_raw_only' if summary['complete_raw_assets']
                       else 'partial_raw')}


@update_diagnostics('candidate_root', injected=('observe', 'retrieve', 'extractor'))
def run_auto_catalog(*, download=True, parse=True, observe=None, retrieve=None,
                     previous_finder=None, extractor=None,
                     manifest_root=None, bundle_root=None, candidate_root=None,
                     max_download_bytes=DEFAULT_MAX_DOWNLOAD_BYTES,
                     max_downloads=DEFAULT_MAX_DOWNLOADS, opener=None,
                     progress=None):
    """One bounded background iteration; no UI objects, network commands or login.

    parse=True is only allowed with download=True; both default on for LaLa's
    auto-prepare worker. Call download=False,parse=False for a safe preview.
    """
    if progress is not None and not callable(progress):
        raise AutoCatalogError('Invalid Launcher progress callback')

    def emit(phase, **details):
        if progress is not None:
            progress(phase, details)

    default_extractor = extractor is None
    if parse and not download:
        raise AutoCatalogError('Cannot parse before explicit verified Bundle sync')
    if (type(max_download_bytes) is not int or max_download_bytes < 0
            or type(max_downloads) is not int or max_downloads < 0):
        raise AutoCatalogError('Invalid automatic download limits')
    # Persist only verified public version identifiers in a real Launcher run.
    # Injected test fixtures must never read or overwrite the user's cache.
    real_observation = observe is None and retrieve is None
    observe = observe_official_versions if observe is None else observe
    retrieve = fetch_official_manifest if retrieve is None else retrieve
    previous_finder = (find_previous_verified_manifest if previous_finder is None
                       else previous_finder)
    emit('official_version')
    snapshot = observe()
    manifests, previous = {}, {}
    for package in PACKAGES:
        emit('manifest', package=package)
        current = retrieve(spec_from_snapshot(snapshot, package),
                           cache_root=manifest_root)
        manifests[package] = current
        previous[package] = previous_finder(current, cache_root=manifest_root)
    if download:
        # .version can change while the two .bytes/.hash pairs are fetched.
        # Never begin Bundle work using a mixed-version observation. Check
        # the complete official version tuple again; timestamp is irrelevant.
        # This intentionally requires only ResourcePath_PC.dat + .version,
        # not optional official .json / .report sources.
        from wlre.services.official_resource_sync import validate_snapshot
        try:
            latest = validate_snapshot(observe())
        except (ValueError, OSError, TypeError, KeyError) as exc:
            raise AutoCatalogError(
                'Official version recheck failed; no Bundle work started') from exc
        if any(latest[key] != snapshot[key]
               for key in ('data_ver', 'exe_version', 'packages')):
            raise AutoCatalogError(
                'Official package version changed during Manifest sync; '
                'no Bundle work started')
    emit('bundle_plan')
    bindings = _bindings_for_snapshot(snapshot)
    plan = plan_catalog_pipeline(snapshot, manifests, bindings,
                                 previous_manifests=previous, bundle_root=bundle_root)
    record_identity(plan.identity.key)
    # Compare the current fully checked Manifest identity with the last
    # OBSERVED official revision, not with an installed or gameplay-approved
    # revision. Saving this metadata never switches the active game runtime.
    revision_status = 'unrecorded'
    if real_observation and download:
        from wlre.services.official_resource_sync import (
            OfficialSyncError, compare_snapshot, read_snapshot, save_snapshot,
        )
        try:
            previous_observation = read_snapshot()
        except OfficialSyncError:
            previous_observation = None
        delta = compare_snapshot(snapshot, previous_observation)
        revision_status = (
            'first_observation' if previous_observation is None
            else 'changed' if (
                delta['data_ver_changed'] or delta['exe_version_changed'] or
                any(change == 'changed' for change in delta['package_changes'].values()))
            else 'unchanged')
        try:
            save_snapshot(snapshot)
        except OSError:
            # A read-only user profile must not turn valid official manifests
            # into an unsafe runtime decision; this status is informational.
            emit('official_revision_unavailable')
        emit('official_revision', state=revision_status,
             data= snapshot['packages']['DataPackage'].split('_', 1)[0],
             main= snapshot['packages']['MainPackage'].split('_', 1)[0])
    result = {
        'catalog_key': plan.catalog_key, 'data_ver': plan.identity.data_ver,
        'official_revision_status': revision_status,
        'features': list(FEATURES),
        'status': 'preview', 'approved': False,
        'assets_ready': False, 'can_send_packets': False,
        'downloads_required': sum(p.download_count for p in plan.updates),
        'download_bytes': sum(p.download_bytes for p in plan.updates),
    }
    # Build the current two-Package path/category index from already verified
    # Manifests even when optional Bundle downloads later fail.
    if download and default_extractor:
        result['classification'] = _refresh_existing_classification(
            plan.identity, manifests, candidate_root, progress)
    # Keep synchronizing raw data even when the audited four-feature Eve or
    # ItemData adapter later refuses a newly changed official schema.
    # The raw inventory remains private, never a formal login source.
    if download and default_extractor:
        result['resource_rebuild'] = _rebuild_known_resources(
            result, identity=plan.identity, manifests=manifests,
            bundle_root=bundle_root, candidate_root=candidate_root,
            max_download_bytes=max_download_bytes,
            max_downloads=max_downloads, opener=opener, progress=progress)
        result['classification'] = _refresh_existing_classification(
            plan.identity, manifests, candidate_root, progress)
    if not download:
        emit('preview_ready')
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
    emit('bundle_sync', count=result['downloads_required'],
         bytes=result['download_bytes'])
    sync, _ = run_catalog_pipeline(
        plan, download=True, extractor=None, bundle_root=bundle_root,
        max_download_bytes=max_download_bytes, max_downloads=max_downloads,
        opener=opener,
        progress=(None if progress is None else
                  lambda completed, total, action: emit(
                      'bundle_item', completed=completed, total=total,
                      action=action)))
    result['verified_bundles'] = sum(len(p.entries) for p in plan.updates)
    if not parse:
        emit('download_ready')
        return {**result, 'status': 'downloaded_unparsed'}
    emit('bundle_verify')
    paths = verified_source_paths(plan, bundle_root=bundle_root)
    raw_by_feature, parsed = {}, {}
    revisions = {p.name: p.full_version for p in plan.identity.packages}
    # All source digests computed AFTER official MD5/CRC checks. Self-computed
    # SHA does not constitute independent release approval.
    for source in plan.sources:
        provisional = source.binding
        feature = provisional.contract.feature
        emit('extract', feature=feature)
        # Report reviewed, human-readable decoder errors without dumping file
        # paths, full tracebacks, binary payloads, or UnityPy internals.
        from wlre.services.world.unity_textasset import UnityTextAssetError
        from wlre.services.world.eve_v115 import EveDecodeError
        from wlre.services.world.itemdata_v1 import ItemDataDecodeError
        try:
            raw = extractor(provisional, paths[feature])
        except (UnityTextAssetError, EveDecodeError, ItemDataDecodeError) as exc:
            stage = ('UnityFS／TextAsset' if isinstance(exc, UnityTextAssetError)
                     else 'Eve 二進位事件' if isinstance(exc, EveDecodeError)
                     else 'ItemData 二進位表')
            emit('extract_failed', feature=feature, stage=stage)
            raise AutoCatalogError(
                f'{feature} {stage} 解析失敗：{exc}；未啟用任何未驗證的正式資料') from exc
        except Exception as exc:
            emit('extract_failed', feature=feature, stage='未分類解包例外')
            raise AutoCatalogError(
                f'{feature} 來源解包發生未分類例外（{type(exc).__name__}），'
                '請提供診斷資訊；未啟用任何未驗證的正式資料') from exc
        try:
            if type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_BYTES:
                raise CatalogAdapterError('Extractor returned invalid source bytes')
            digest = hashlib.sha256(raw).hexdigest()
            contract = SourceContract(
                feature, provisional.contract.source_name,
                provisional.contract.schema_id, digest,
                provisional.contract.package, provisional.contract.package_version)
            parsed[feature] = parse_feature(catalog_key=plan.catalog_key,
                                            package_versions=revisions,
                                            contract=contract, raw=raw)
        except CatalogAdapterError as exc:
            emit('extract_failed', feature=feature, stage='資料 Schema')
            raise AutoCatalogError(
                f'{feature} 資料 Schema 校驗失敗：{exc}；未啟用任何未驗證的正式資料') from exc
        except Exception as exc:
            emit('extract_failed', feature=feature, stage='未分類 Schema 例外')
            raise AutoCatalogError(
                f'{feature} Schema 校驗發生未分類例外（{type(exc).__name__}），'
                '請提供診斷資訊；未啟用任何未驗證的正式資料') from exc
        raw_by_feature[feature] = raw
    if set(parsed) != set(FEATURES):
        raise AutoCatalogError('Official source set is incomplete')
    # Store verified source metadata atomically. Never create candidate.zip,
    # and never infer gameplay or protocol approval from a successful parse.
    from wlre.services.world.official_catalog_store import store_official_catalog
    root = Path(candidate_root) if candidate_root is not None else data_root() / 'official_sync'
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / 'official_catalog.sqlite3'
    store_official_catalog(db_path, parsed)
    emit('official_catalog_stored')
    return {**result, 'status': 'verified_official',
            'data_compatibility': 'compatible',
            'protocol_compatibility': 'unverified',
            'record_counts': {f: parsed[f].record_count for f in FEATURES}}
