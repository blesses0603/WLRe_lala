"""Activate the audited 1275 LaLa catalog directly from verified official Bundles.

This is a real runtime data source, not a candidate display index. Every source
is reconstructed on demand from a Bundle whose MD5/CRC matches a release-pinned
official YooAsset Manifest. It does not itself authorize network packets.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

from wlre.storage.paths import data_root

# These two independent Manifest SHA-256 values are taken from reviewed 1275
# official .bytes with matching .hash (CRC32 LE); NOT from a self-generated
# candidate ZIP or the untrusted .json/.report sidecar.
_PINNED_MANIFEST_SHA256 = {
    'DataPackage': '8af6b9374d2e31e5bda4d82d2ec4be6b3a673e9188a522eb2c1b110e68c51dee',
    'MainPackage': '65da10fab29b8ce96247a18e611ee0ba3c5c3bc5cb71a42c4e177001a8c4ba49',
}
_PINNED_DATA_VER = '1.3.21'
_REQUIRED_TABLES = (
    'Eve', 'ItemData_C', 'TalkData_C', 'TextData_C',
    'SmithData_C', 'ScenesData_C',
    'AdventureData_C', 'AdventureLvData_C',
    'NpcData_C', 'NpcCareerData_C',
)
# Optional: source-verified portal metadata. An absent or changed layout never
# breaks the core ten-table NPC/recipe runtime or enables game packets.
_PORTAL_TABLES = ('StageMapData_C', 'EveDoorLinks')
_OPTIONAL_ROUTE_TABLES = ('DoorLinkData_C',)
_ASSET_ROOT = 'Assets/ResourcesBuild/Data/'


class BundleRuntimeUnavailable(ValueError):
    """A complete audited 1275 runtime could not be constructed safely."""


def sync_pinned_runtime_bundles(*, sync_root=None,
                                observe=None, retrieve=None,
                                execute=None, max_download_bytes=32 * 1024 * 1024,
                                max_downloads=24):
    """Only sync audited 1275 runtime dependencies, independent of preview.

    Retrieves no official .json/.report and never edits installed game files.
    Two fresh .version observations, both .bytes/.hash verifications and
    independent pinned SHA-256 comparisons precede Bundle downloads.
    This prepares *bytes*, not an authorization to log in or send packets.
    """
    from wlre.services.official_resource_sync import (
        observe_official_versions, validate_snapshot)
    from wlre.services.official_manifest_sync import (
        ManifestSpec, fetch_official_manifest, MAX_MANIFEST_BYTES)
    from wlre.services.official_incremental_sync import (
        build_update_plan, execute_update_plan)
    from wlre.services.official_bundle_download import _verified_file
    from wlre.services.resource_compatibility import load_supported_resources

    if (type(max_downloads) is not int or not 0 <= max_downloads <= 24
            or type(max_download_bytes) is not int
            or not 0 <= max_download_bytes <= 32 * 1024 * 1024):
        raise BundleRuntimeUnavailable('1275 Bundle 下載額度設定無效')
    observe = observe_official_versions if observe is None else observe
    retrieve = fetch_official_manifest if retrieve is None else retrieve
    execute = execute_update_plan if execute is None else execute
    root = Path(sync_root) if sync_root is not None else data_root() / 'official_sync'
    baseline = load_supported_resources()
    packages = baseline['packages']
    try:
        start = validate_snapshot(observe())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise BundleRuntimeUnavailable('無法確認官方 1275 版本，停止 Bundle 下載') from exc
    if (start['data_ver'] != _PINNED_DATA_VER or
            start['exe_version'] != baseline['official_game_exe_version'] or
            any(start['packages'][p] != packages[p]['manifest']
                or packages[p]['revision'] != '1275'
                for p in _PINNED_MANIFEST_SHA256)):
        raise BundleRuntimeUnavailable('官方版本不符合此版固定的 1275 Runtime')
    manifests = {}
    for package in ('DataPackage', 'MainPackage'):
        spec = ManifestSpec(start['data_ver'], package,
                            packages[package]['manifest'])
        try:
            current = retrieve(spec, cache_root=root / 'manifests')
            with current.cache_path.open('rb') as stream:
                raw = stream.read(MAX_MANIFEST_BYTES + 1)
        except (OSError, ValueError, KeyError) as exc:
            raise BundleRuntimeUnavailable(
                '官方 Manifest 下載或快取驗證失敗：' + package) from exc
        if (current.spec != spec or not 0 < len(raw) <= MAX_MANIFEST_BYTES
                or hashlib.sha256(raw).hexdigest() !=
                _PINNED_MANIFEST_SHA256[package]):
            raise BundleRuntimeUnavailable(
                '固定 1275 Manifest SHA-256 核對失敗：' + package)
        manifests[package] = current
    try:
        latest = validate_snapshot(observe())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise BundleRuntimeUnavailable('官方版本再次確認失敗，拒絕下載 Bundle') from exc
    if any(latest[k] != start[k]
           for k in ('data_ver', 'exe_version', 'packages')):
        raise BundleRuntimeUnavailable('官方更新期間版本變動，拒絕混用 Bundle')

    from wlre.services.official_incremental_sync import IncrementalSyncError
    asset_paths = tuple(_ASSET_ROOT + name + '.bytes'
                        for name in _REQUIRED_TABLES)
    try:
        plan = build_update_plan(
            manifests['DataPackage'], asset_paths=asset_paths,
            cache_root=root / 'bundles')
        count = sum(entry.action != 'cached' for entry in plan.entries)
        needed = sum(entry.spec.file_size for entry in plan.entries
                     if entry.action != 'cached')
        if count > max_downloads or needed > max_download_bytes:
            raise BundleRuntimeUnavailable(
                '必要官方 1275 Bundle 超過本輪安全下載額度')
        execute(plan, cache_root=root / 'bundles', download=True,
                max_download_bytes=max_download_bytes,
                max_downloads=max_downloads)
        if any(not _verified_file(entry.spec.cache_path(root / 'bundles'),
                                  entry.spec) for entry in plan.entries):
            raise BundleRuntimeUnavailable('已下載 Bundle 再驗證失敗')
    except BundleRuntimeUnavailable:
        raise
    except (OSError, ValueError, TypeError, KeyError,
            RuntimeError, IncrementalSyncError) as exc:
        raise BundleRuntimeUnavailable('必要官方 1275 Bundle 同步失敗') from exc

    # StageMapData_C is independently useful for human-facing portal names.
    # Never let an unavailable EveDoorLinks consume the entire optional sync
    # budget or prevent StageMapData from being cached.
    remaining_count = max_downloads - count
    remaining_bytes = max_download_bytes - needed
    portal_count, portal_bytes = 0, 0
    portal_available = {}
    portal_failures = {}
    for table in _PORTAL_TABLES + _OPTIONAL_ROUTE_TABLES:
        try:
            optional_plan = build_update_plan(
                manifests['DataPackage'],
                asset_paths=(_ASSET_ROOT + table + '.bytes',),
                cache_root=root / 'bundles')
            needed_count = sum(entry.action != 'cached'
                               for entry in optional_plan.entries)
            needed_bytes = sum(entry.spec.file_size
                               for entry in optional_plan.entries
                               if entry.action != 'cached')
            if not optional_plan.entries:
                portal_failures[table] = 'asset_missing_from_manifest'
                continue
            if needed_count > remaining_count or needed_bytes > remaining_bytes:
                portal_failures[table] = 'download_budget_exhausted'
                continue
            execute(optional_plan, cache_root=root / 'bundles', download=True,
                    max_download_bytes=remaining_bytes,
                    max_downloads=remaining_count)
            if not all(_verified_file(
                    row.spec.cache_path(root / 'bundles'), row.spec)
                    for row in optional_plan.entries):
                portal_failures[table] = 'bundle_integrity_failed'
                continue
            portal_available[table] = True
            portal_count += needed_count
            portal_bytes += needed_bytes
            remaining_count -= needed_count
            remaining_bytes -= needed_bytes
        except (OSError, ValueError, TypeError, KeyError,
                RuntimeError, IncrementalSyncError):
            portal_failures[table] = 'bundle_sync_failed'
    return {'verified_bundles': len(plan.entries),
            'downloaded_bundles': count,
            'bytes_downloaded': needed,
            'portal_metadata_ready': all(
                portal_available.get(table) for table in _PORTAL_TABLES),
            'portal_names_bundle_ready': bool(
                portal_available.get('StageMapData_C')),
            'portal_route_bundle_ready': bool(
                portal_available.get('DoorLinkData_C')),
            'portal_bundles_downloaded': portal_count,
            'portal_bytes_downloaded': portal_bytes,
            'portal_sync_failures': portal_failures,
            'assets_ready': False, 'can_send_packets': False}


def load_verified_bundle_runtime(*, sync_root=None):
    """Load working NPC/shop/item/crafting/scene data without manual ZIPs.

    No network access or download occurs here. This call independently checks
    the two release-baseline Manifest versions and pinned SHA-256 digests,
    verified local .bytes/.hash receipts, every required Bundle's hash/CRC,
    and each decoded TextAsset's audited layout. Launcher four-feature
    candidates do NOT authorize this runtime or prevent its verification.
    """
    from wlre.services.resource_compatibility import load_supported_resources
    from wlre.services.official_manifest_sync import (
        ManifestSpec, ManifestSyncError, read_verified_cached_manifest,
        MAX_MANIFEST_BYTES)
    from wlre.services.official_bundle_download import _verified_file
    from wlre.services.official_incremental_sync import build_update_plan
    from wlre.services.world.official_catalog_pipeline import AssetBinding
    from wlre.services.world.catalog_adapters import SourceContract
    from wlre.services.world.unity_textasset import extract_textasset, _loader
    from wlre.services.world.preview_1275 import (
        Preview1275, PreviewNPCIndex, PreviewInteractIndex, parse_smith_1275)
    from wlre.services.world.itemdata_v1 import parse_itemdata
    from wlre.services.world.npc_talk import parse_talk_data
    from wlre.services.expedition.data import (
        parse_text_data, parse_catalog as parse_expedition,
        parse_npcs as parse_expedition_npcs,
        ADVENTURE_1275_SHA256, ADVENTURE_LEVEL_1275_SHA256)
    from wlre.services.world.eve_v115 import derive_eve_index
    from wlre.services.world.doors_1275 import (
        SOURCE_SHA256 as EVE_SHA256, parse_doors_1275)
    from wlre.services.instance_catalog import parse_stages
    from wlre.services.world.scene_names_1275 import bind_scene_names
    from wlre.services.world.portal_schema import recognize_portal_source
    from wlre.services.world.portal_links_1275 import (verified_portal_destinations,
                                                      verified_portal_names,
                                                      verified_portal_positions,
                                                      read_only_portal_destinations)

    root = Path(sync_root) if sync_root is not None else data_root() / 'official_sync'
    # An optional four-feature *candidate* may be incomplete when the Eve
    # adapter encounters an unsupported layout, even while the independently
    # pinned ten-table Bundle runtime is valid. Do not use the Launcher status
    # or self-generated candidate ZIP as an authorization token.
    #
    # This path performs NO network requests. The separate pre-login online
    # version gate must confirm the server still uses this release baseline.
    baseline = load_supported_resources()
    versions = baseline['packages']
    if (set(versions) != set(_PINNED_MANIFEST_SHA256) or
            any(versions[p]['revision'] != '1275'
                for p in _PINNED_MANIFEST_SHA256)):
        raise BundleRuntimeUnavailable('LaLa 內建正式 1275 版本基準不符')
    private_manifests = root / 'manifests'
    manifests = {}
    for package in ('DataPackage', 'MainPackage'):
        spec = ManifestSpec(_PINNED_DATA_VER, package,
                            versions[package]['manifest'])
        try:
            verified = read_verified_cached_manifest(
                spec, cache_root=private_manifests)
        except (ManifestSyncError, OSError) as exc:
            raise BundleRuntimeUnavailable(
                '缺少已驗證的官方 Manifest 快取：' + package) from exc
        try:
            with verified.cache_path.open('rb') as handle:
                raw = handle.read(MAX_MANIFEST_BYTES + 1)
        except OSError as exc:
            raise BundleRuntimeUnavailable(
                '已驗證的 Manifest 檔案不存在：' + package) from exc
        if (verified.spec != spec or not 0 < len(raw) <= MAX_MANIFEST_BYTES
                or hashlib.sha256(raw).hexdigest() != _PINNED_MANIFEST_SHA256[package]):
            raise BundleRuntimeUnavailable(
                '官方 Manifest 不是本版經獨立 SHA-256 審核的內容：' + package)
        manifests[package] = verified

    verified_data = manifests['DataPackage']
    bundle_root = root / 'bundles'
    load_container = lru_cache(maxsize=3)(_loader)
    sources = {}
    stage = '原始資料'
    try:
        for table in _REQUIRED_TABLES:
            stage = table
            asset = _ASSET_ROOT + table + '.bytes'
            plan = build_update_plan(
                verified_data, asset_paths=(asset,), cache_root=bundle_root)
            if not plan.entries or any(entry.action != 'cached' for entry in plan.entries):
                raise BundleRuntimeUnavailable('仍缺少官方 Bundle：' + table)
            paths = tuple(entry.spec.cache_path(bundle_root) for entry in plan.entries)
            if any(not _verified_file(path, row.spec)
                   for path, row in zip(paths, plan.entries)):
                raise BundleRuntimeUnavailable('Bundle 來源校驗失敗：' + table)
            binding = AssetBinding(
                asset, SourceContract(
                    'scenes', table, 'stage-new-76-v1',
                    '0' * 64, 'DataPackage', verified_data.spec.package_version))
            sources[table] = extract_textasset(binding, paths, loader=load_container)

        stage = 'Eve'
        eve = sources['Eve']
        if hashlib.sha256(eve).hexdigest() != EVE_SHA256:
            raise BundleRuntimeUnavailable('1275 Eve 來源 SHA-256 不符')
        npc = json.loads(derive_eve_index(eve, 'EventData.NewNpc'))
        interacts = json.loads(derive_eve_index(eve, 'EventData.NewInteract'))
        if (npc.get('record_count') != 10975
                or interacts.get('record_count') != 1634
                or len(npc.get('scenes', {})) != 1262):
            raise BundleRuntimeUnavailable('NPC／互動事件數不符合已審核 1275 資料')
        stage = 'ItemData_C'
        items = parse_itemdata(sources['ItemData_C'])
        stage = 'TalkData_C'
        talk_rows = parse_talk_data(sources['TalkData_C'])
        stage = 'TextData_C'
        texts = parse_text_data(sources['TextData_C'])
        stage = 'SmithData_C'
        recipes = parse_smith_1275(sources['SmithData_C'])
        stage = 'ScenesData_C'
        scene_rows = parse_stages(sources['ScenesData_C'])
        stage = 'Eve'
        doors = parse_doors_1275(eve)
        portal_destinations, portal_names, portal_positions = {}, {}, {}
        portal_display_destinations = {}
        portal_link_evidence = {}
        portal_extra_routes = []
        portal_metadata_status = 'missing_stage_map'
        optional = {}
        optional_failures = {}
        portal_schema_report = {}
        # Each optional Bundle must be traceable to a verified official
        # manifest. Do not erase failures with a silent 'continue': users need
        # to distinguish not-downloaded, damaged and unsupported TextAssets.
        for table in _PORTAL_TABLES + _OPTIONAL_ROUTE_TABLES:
            try:
                asset = _ASSET_ROOT + table + '.bytes'
                portal_plan = build_update_plan(
                    verified_data, asset_paths=(asset,), cache_root=bundle_root)
                if not portal_plan.entries:
                    optional_failures[table] = 'asset_missing_from_manifest'
                    continue
                if any(row.action != 'cached' for row in portal_plan.entries):
                    optional_failures[table] = 'bundle_not_cached'
                    continue
                paths = tuple(row.spec.cache_path(bundle_root)
                              for row in portal_plan.entries)
                if any(not _verified_file(path, row.spec)
                       for path, row in zip(paths, portal_plan.entries)):
                    optional_failures[table] = 'bundle_integrity_failed'
                    continue
                binding = AssetBinding(
                    asset, SourceContract(
                        'scenes', table, 'stage-new-76-v1',
                        '0' * 64, 'DataPackage', verified_data.spec.package_version))
                payload = extract_textasset(binding, paths, loader=load_container)
                verdict = recognize_portal_source(table, payload)
                portal_schema_report[table] = verdict
                if verdict['status'] != 'recognized':
                    optional_failures[table] = 'layout_unrecognized'
                    continue
                optional[table] = payload
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                # Never disclose filesystem paths or untrusted raw errors.
                optional_failures[table] = 'textasset_extract_failed'
                continue
        if 'StageMapData_C' not in optional:
            portal_metadata_status = optional_failures.get(
                'StageMapData_C', 'missing_stage_map')
        if 'StageMapData_C' in optional:
            try:
                portal_names = verified_portal_names(
                    optional['StageMapData_C'], scene_rows, texts)
                portal_metadata_status = 'stage_map_ready'
                if 'EveDoorLinks' in optional:
                    try:
                        from wlre.services.world.portal_evidence_1275 import (read_only_portal_evidence)
                        portal_link_evidence = read_only_portal_evidence(
                            optional['StageMapData_C'], optional['EveDoorLinks'],
                            doors, scene_rows)
                        portal_positions = verified_portal_positions(
                            optional['StageMapData_C'], optional['EveDoorLinks'],
                            doors, scene_rows)
                        portal_display_destinations = read_only_portal_destinations(
                            optional['StageMapData_C'], optional['EveDoorLinks'],
                            doors, scene_rows)
                        portal_destinations = verified_portal_destinations(
                            optional['StageMapData_C'], optional['EveDoorLinks'],
                            doors, scene_rows)
                        portal_metadata_status = 'destination_links_loaded'
                    except (ValueError, KeyError, TypeError):
                        portal_metadata_status = 'destination_links_missing_or_invalid'
                else:
                    portal_metadata_status = (
                        'destination_links_' + optional_failures['EveDoorLinks']
                        if 'EveDoorLinks' in optional_failures
                        else 'destination_links_missing_or_invalid')
            except (ValueError, KeyError, TypeError):
                portal_metadata_status = 'stage_map_invalid'
        # EveDoorLinks is independently useful for read-only routes even
        # when the StageMap marker table has not been downloaded.
        if not portal_link_evidence and 'EveDoorLinks' in optional:
            try:
                from wlre.services.world.portal_evidence_1275 import (
                    read_only_portal_evidence)
                portal_link_evidence = read_only_portal_evidence(
                    optional.get('StageMapData_C'),
                    optional['EveDoorLinks'], doors, scene_rows)
            except (ValueError, TypeError, KeyError):
                pass
        # DoorLinkData has coordinates and destination IDs, but no C20-8
        # event index. Keep its route network separate from ordinary doors.
        if 'DoorLinkData_C' in optional:
            try:
                from wlre.services.world.portal_evidence_1275 import (
                    read_only_door_link_routes)
                portal_extra_routes = read_only_door_link_routes(
                    optional['DoorLinkData_C'], scene_rows)
            except (ValueError, TypeError, KeyError):
                portal_schema_report['DoorLinkData_C'] = {
                    'status': 'layout_unrecognized', 'can_send_packets': False}
        if len(recipes) != 1032 or any(
                ident not in items or type(items[ident].get('open_used')) is not int
                for ident in recipes):
            raise BundleRuntimeUnavailable('1275 製作配方與物品開放狀態未完成交叉驗證')
        if not scene_rows or not talk_rows or not texts:
            raise BundleRuntimeUnavailable('1275 場景或對話原始資料缺失')

        # Expedition is a real service catalog, not just a candidate label.
        # This is the same independently audited 1275 source identity that
        # the older full-ZIP loader validates before expedition dispatch.
        stage = 'AdventureData_C／AdventureLvData_C'
        if (hashlib.sha256(sources['AdventureData_C']).hexdigest()
                != ADVENTURE_1275_SHA256 or
                hashlib.sha256(sources['AdventureLvData_C']).hexdigest()
                != ADVENTURE_LEVEL_1275_SHA256):
            raise BundleRuntimeUnavailable('1275 遠征任務／等級來源 SHA-256 不符')
        expedition = parse_expedition(
            sources['AdventureData_C'], sources['AdventureLvData_C'])
        stage = 'NpcData_C／NpcCareerData_C'
        expedition_npcs = parse_expedition_npcs(
            sources['NpcData_C'], sources['NpcCareerData_C'])
        if (len(expedition['tasks']) != 260
                or len(expedition['levels']) != 10
                or len(expedition_npcs) != 7561):
            raise BundleRuntimeUnavailable('1275 遠征任務／夥伴資料筆數不符')
        stage = 'TextData_C／遠征名稱'
        named = {}
        for key, quest in expedition['tasks'].items():
            name = texts.get(quest['name_id'])
            area = texts.get(quest['area_name'], '')
            if (type(name) is not str or not name.strip()
                    or type(area) is not str
                    or len(name) > 8192 or len(area) > 8192):
                raise BundleRuntimeUnavailable('1275 遠征任務缺少已驗證文字')
            named[key] = {**quest, 'name': name, 'area_label': area}
        expedition = {
            **expedition, 'tasks': named, 'npcs': expedition_npcs,
            'revision': 1275,
            'source_kind': 'verified_1275_official_bundle',
            'source_sha256': {
                **expedition['source_sha256'],
                'NpcData_C': hashlib.sha256(sources['NpcData_C']).hexdigest(),
                'NpcCareerData_C': hashlib.sha256(sources['NpcCareerData_C']).hexdigest(),
            },
        }

        stage = '正式 Runtime 建立'
        from wlre.services.world.portal_coverage import audit_portal_coverage
        coverage = audit_portal_coverage(doors, scene_rows,
            optional.get('StageMapData_C'), optional.get('EveDoorLinks'),
            portal_positions, portal_destinations, portal_names,
            portal_link_evidence, portal_extra_routes)
        return Preview1275(
            npc_index=PreviewNPCIndex(npc),
            interact_index=PreviewInteractIndex(interacts),
            items=items,
            talks={int(k): v['text'] for k, v in talk_rows.items()},
            texts=texts,
            recipes=recipes,
            scene_ids=frozenset(scene_rows),
            stages=scene_rows,
            scene_names=bind_scene_names(scene_rows, texts),
            portal_destinations=portal_destinations,
            portal_names=portal_names,
            portal_positions=portal_positions,
            portal_display_destinations=portal_display_destinations,
            portal_link_evidence=portal_link_evidence,
            portal_extra_routes=portal_extra_routes,
            portal_metadata_status=portal_metadata_status,
            portal_schema_report=portal_schema_report,
            portal_coverage=coverage,
            doors=doors, expedition=expedition,
        )
    except BundleRuntimeUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise BundleRuntimeUnavailable(
            '官方 Bundle 的資料格式無法建立完整 1275 Runtime：' + stage) from exc
