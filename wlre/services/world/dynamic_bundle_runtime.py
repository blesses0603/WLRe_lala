"""Version-pair-aware, read-only runtime catalog metadata for current official assets.

The live official version pair is authoritative; historical 1275 constants are
not used. Parsed record counts are sourced from verified TextAssets stored by
the official catalog pipeline, never inferred from a Manifest asset count.
This does not grant gameplay or network protocol approval.
"""
from __future__ import annotations

from wlre.services.parser_diagnostics import diagnosed, update_diagnostics, record_identity

import re
from dataclasses import dataclass

from wlre.services.world.catalog_adapters import FEATURES
from wlre.services.world.catalog_runtime import official_catalog_key, official_package_versions
from wlre.services.world.official_catalog_store import active_official_catalog

_HEX = re.compile(r'[0-9a-f]{64}\Z')


class DynamicRuntimeUnavailable(ValueError):
    """Official runtime metadata is absent, stale, or incomplete."""


@dataclass(frozen=True)
class DynamicRuntime:
    catalog_key: str
    package_versions: dict[str, str]
    record_counts: dict[str, int]
    source_sha256: dict[str, str]
    assets_ready: bool = False
    can_send_packets: bool = False


def load_dynamic_runtime_metadata(remote, *, db_path):
    """Select only the exact official version pair from the verified SQLite cache.

    The record_count columns were checked against parsed payloads by the
    catalog pipeline before transactional storage. This function does not
    treat editable local SQLite metadata as a trust anchor for gameplay.
    """
    try:
        versions = official_package_versions(remote)
        key = official_catalog_key(remote)
    except (ValueError, KeyError, TypeError) as exc:
        raise DynamicRuntimeUnavailable('Official version pair unavailable') from exc
    catalog = active_official_catalog(db_path)
    if not catalog or catalog['catalog_key'] != key:
        raise DynamicRuntimeUnavailable('Verified current-version catalog unavailable')
    sources = catalog['sources']
    if set(sources) != set(FEATURES):
        raise DynamicRuntimeUnavailable('Official source set incomplete')
    counts, digests = {}, {}
    for feature in FEATURES:
        row = sources[feature]
        count, digest = row['record_count'], row['sha256']
        if (type(count) is not int or not 0 <= count <= 20000
                or type(digest) is not str or not _HEX.fullmatch(digest)):
            raise DynamicRuntimeUnavailable('Official source metadata invalid')
        counts[feature] = count
        digests[feature] = digest
    return DynamicRuntime(key, versions, counts, digests)


def load_parsed_dynamic_runtime(remote, *, parsed):
    """Accept complete independently parsed current-version records, not counts."""
    from wlre.services.world.catalog_adapters import FEATURES, ParsedCatalog
    try:
        key = official_catalog_key(remote)
        versions = official_package_versions(remote)
        if type(parsed) is not dict or set(parsed) != set(FEATURES):
            raise DynamicRuntimeUnavailable('Incomplete parsed source set')
        for feature in FEATURES:
            item = parsed[feature]
            if (type(item) is not ParsedCatalog or item.feature != feature
                    or item.catalog_key != key or item.assets_ready is not False
                    or item.can_send_packets is not False):
                raise DynamicRuntimeUnavailable('Unverified runtime source')
        return {
            'catalog_key': key,
            'package_versions': versions,
            'records': {f: parsed[f].records for f in FEATURES},
            'record_counts': {f: parsed[f].record_count for f in FEATURES},
            'assets_ready': False,
            'can_send_packets': False,
        }
    except (ValueError, TypeError, KeyError) as exc:
        raise DynamicRuntimeUnavailable('Dynamic runtime unavailable') from exc


# Process-local activation is rebuilt from official manifests and raw Bundles.
# Neither SQLite metadata nor launcher receipts may populate this slot.
_active = None
_attempted = False
_generation = 0
from threading import RLock
_activation_lock = RLock()


def current_runtime():
    return _active


def dynamic_attempted():
    return _attempted



def current_catalog_token():
    """Identity for cached consumers, including a failed/invalidated runtime."""
    runtime=current_runtime()
    identity=getattr(runtime,'catalog_identity',None)
    return (dynamic_attempted(),getattr(identity,'key',None))


def invalidate_runtime():
    global _active, _attempted, _generation
    with _activation_lock:
        _active, _attempted = None, True
        _generation += 1
        from wlre.services.items.crafting import RECIPES
        RECIPES.clear()
        from wlre.services.world.portal_policy import smallmaps
        smallmaps.cache_clear()
        from wlre.services.world.npc_item_data import item_catalog
        item_catalog.cache_clear()
        return _generation


@diagnosed('runtime-recipes-v1')
def parse_runtime_recipes(raw, items):
    """Recognize reviewed 33/35-byte layouts; preserve every recipe identity.

    The legacy product-keyed UI cannot choose between several recipe IDs.
    Ambiguous products remain in recipe_catalog and are excluded from that UI.
    Keep conditional read-only flags; unconditional records use the matching wire layout.
    """
    import struct
    from wlre.services.world.smith_candidate import parse_smith_records
    if type(raw) is not bytes or len(raw) < 4:
        raise DynamicRuntimeUnavailable('Missing Smith table')
    count = struct.unpack_from('<i', raw)[0]
    if not 1 <= count <= 20000:
        raise DynamicRuntimeUnavailable('Invalid Smith record count')
    rows = parse_smith_records(raw)
    from collections import Counter
    counts = Counter(r['item_id'] for r in rows)
    checked = []
    for row in rows:
        item = items.get(row['item_id'])
        if (type(item) is not dict or type(item.get('open_used')) is not int
                or any(m['item_id'] not in items or not m['count']
                       for m in row['materials'])):
            raise DynamicRuntimeUnavailable('Recipe references missing ItemData')
        checked.append({**row, 'open_used': item['open_used']})
    return {r['item_id']: r for r in checked if counts[r['item_id']] == 1}, checked


@update_diagnostics('sync_root', injected=('observe', 'retrieve', 'execute'))
def prepare_dynamic_runtime(*, sync=False, sync_root=None, observe=None,
                            retrieve=None, execute=None,
                            max_download_bytes=32 * 1024 * 1024,
                            max_downloads=24, max_image_download_bytes=64*1024*1024,
                            max_image_downloads=4, max_emoji_download_bytes=32*1024*1024,
                            max_emoji_downloads=8):
    """Official observation -> verified manifests/Bundles -> complete runtime.

    Verification is performed on every load, including cache hits. Downloading
    is bounded and only allowed by the launcher's explicit sync=True call.
    Publishing happens after parsing AND a second live version observation.
    No packet permission or local compatibility declaration is changed.
    """
    from pathlib import Path
    from wlre.storage.paths import data_root
    from wlre.services.official_resource_sync import observe_official_versions, validate_snapshot
    from wlre.services.official_manifest_sync import fetch_official_manifest, spec_from_snapshot, PACKAGES
    from wlre.services.official_incremental_sync import build_update_plan, execute_update_plan
    from wlre.services.world.catalog_identity import identity_from_verified_manifests
    from wlre.services.world.bundle_runtime_1275 import (
        load_verified_bundle_runtime, _REQUIRED_TABLES, _ASSET_ROOT,
        _PORTAL_TABLES, _OPTIONAL_ROUTE_TABLES, _DIAGNOSTIC_TABLES)
    observe = observe_official_versions if observe is None else observe
    retrieve = fetch_official_manifest if retrieve is None else retrieve
    execute = execute_update_plan if execute is None else execute
    root = Path(sync_root) if sync_root is not None else data_root() / 'official_sync'
    if (type(sync) is not bool or type(max_downloads) is not int
            or not 0 <= max_downloads <= 24 or type(max_download_bytes) is not int
            or not 0 <= max_download_bytes <= 32 * 1024 * 1024):
        raise DynamicRuntimeUnavailable('Invalid runtime download budget')
    if (type(max_image_download_bytes) is not int or not 0 <= max_image_download_bytes <= 64*1024*1024
            or type(max_image_downloads) is not int or not 0 <= max_image_downloads <= 4):
        raise DynamicRuntimeUnavailable('Invalid image download budget')
    if (type(max_emoji_download_bytes) is not int or not 0 <= max_emoji_download_bytes <= 32*1024*1024
            or type(max_emoji_downloads) is not int or not 0 <= max_emoji_downloads <= 8):
        raise DynamicRuntimeUnavailable('Invalid emoji download budget')
    before = validate_snapshot(observe())
    manifests = {p: retrieve(spec_from_snapshot(before, p), cache_root=root / 'manifests')
                 for p in PACKAGES}
    identity = identity_from_verified_manifests(before, manifests)
    from wlre.services.world.daily_task_catalog import TABLES as DAILY_TABLES
    from wlre.services.world.guild_catalog import TABLES as GUILD_TABLES
    from wlre.services.world.ark_catalog import TABLES as ARK_TABLES
    from wlre.services.world.instance_runtime import TABLES as INSTANCE_TABLES
    from wlre.services.world.npc_battle_catalog import TABLES as BATTLE_TALK_TABLES
    from wlre.services.world.emoji_database import TABLES as EMOJI_TABLES
    if sync:
        pre_download = validate_snapshot(observe())
        if any(before[k] != pre_download[k] for k in ('data_ver', 'exe_version', 'packages')):
            raise DynamicRuntimeUnavailable('Official versions changed before Bundle sync')
        paths = tuple(_ASSET_ROOT + t + '.bytes' for t in _REQUIRED_TABLES)
        plan = build_update_plan(manifests['DataPackage'], asset_paths=paths,
                                 cache_root=root / 'bundles')
        execute(plan, cache_root=root / 'bundles', download=True,
                max_download_bytes=max_download_bytes, max_downloads=max_downloads)
        # Optional metadata cannot prevent the core runtime from loading.
        left_bytes = max_download_bytes - plan.download_bytes
        left_files = max_downloads - plan.download_count
        for table in BATTLE_TALK_TABLES + INSTANCE_TABLES + _PORTAL_TABLES + _OPTIONAL_ROUTE_TABLES + DAILY_TABLES + GUILD_TABLES + ARK_TABLES + EMOJI_TABLES:
            try:
                optional = build_update_plan(manifests['DataPackage'],
                    asset_paths=(_ASSET_ROOT + table + '.bytes',), cache_root=root / 'bundles')
                if optional.download_bytes > left_bytes or optional.download_count > left_files:
                    continue
                # Reserve attempts even when a download fails.
                left_bytes -= optional.download_bytes
                left_files -= optional.download_count
                execute(optional, cache_root=root / 'bundles', download=True,
                        max_download_bytes=optional.download_bytes,
                        max_downloads=optional.download_count)
            except (OSError, ValueError, RuntimeError):
                pass
    if sync:
        # Image Bundles have a separate bounded budget from core data tables.
        try:
            from wlre.services.world.smallmap_database import image_paths, MAX_DOWNLOAD_BYTES, MAX_DOWNLOADS
            images = build_update_plan(manifests['MainPackage'],
                asset_paths=image_paths(manifests['MainPackage']),cache_root=root/'bundles')
            execute(images,cache_root=root/'bundles',download=True,
                    max_download_bytes=max_image_download_bytes,max_downloads=max_image_downloads)
        except (OSError,ValueError,RuntimeError):
            pass  # Core tables remain available; image loader reports absence.
    if sync:
        try:
            from wlre.services.world.emoji_database import ASSET
            emojis = build_update_plan(manifests['MainPackage'],asset_paths=(ASSET,),cache_root=root/'bundles')
            execute(emojis,cache_root=root/'bundles',download=True,
                    max_download_bytes=max_emoji_download_bytes,max_downloads=max_emoji_downloads)
        except (OSError,ValueError,RuntimeError):
            pass
    if sync:
        try:
            from wlre.services.world.item_image_database import image_paths as item_paths, MAX_DOWNLOAD_BYTES, MAX_DOWNLOADS
            item_images = build_update_plan(manifests['MainPackage'],asset_paths=item_paths(manifests['MainPackage']),cache_root=root/'bundles')
            execute(item_images,cache_root=root/'bundles',download=True,
                    max_download_bytes=MAX_DOWNLOAD_BYTES,max_downloads=MAX_DOWNLOADS)
        except (OSError,ValueError,RuntimeError):
            pass  # Optional images: the loader reports precise unavailable status.
    runtime = load_verified_bundle_runtime(sync_root=root,
                        _verified_context=(before, manifests, identity))
    after = validate_snapshot(observe())
    if any(before[k] != after[k] for k in ('data_ver', 'exe_version', 'packages')):
        raise DynamicRuntimeUnavailable('Official versions changed during runtime load')
    # Re-read manifest bytes after parsing to catch replacement during load.
    if identity_from_verified_manifests(after, manifests) != identity:
        raise DynamicRuntimeUnavailable('Official manifests changed during runtime load')
    return runtime


def activate_for_official(remote, **kwargs):
    """Atomically replace all function data for the freshly observed pair."""
    global _active
    from wlre.services.world.catalog_runtime import official_package_versions
    generation = invalidate_runtime()
    versions = official_package_versions(remote)
    runtime = prepare_dynamic_runtime(**kwargs)
    identity = runtime.catalog_identity
    if (identity.data_ver != remote['resource_path']
            or identity.exe_version != remote['official_exe_version']
            or {p.name: p.full_version for p in identity.packages} != versions):
        raise DynamicRuntimeUnavailable('Runtime does not match pre-login official identity')
    from wlre.services.items.crafting import activate_dynamic_recipes
    with _activation_lock:
        if generation != _generation:
            raise DynamicRuntimeUnavailable('A newer official runtime check superseded this load')
        activate_dynamic_recipes(runtime)
        _active = runtime
    return runtime


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser(description='驗證官方完整動態 Runtime，不登入、不傳送遊戲封包')
    parser.add_argument('--sync', action='store_true', help='下載缺少且通過官方 Manifest 校驗的 Bundle')
    args = parser.parse_args(argv)
    try:
        runtime = prepare_dynamic_runtime(sync=args.sync)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({'status': 'unavailable', 'reason': str(exc),
                          'can_send_packets': False}, ensure_ascii=False))
        return 1
    print(json.dumps({'status': 'verified_runtime',
                      'identity': runtime.catalog_identity.as_dict(),
                      'record_counts': runtime.record_counts,
                      'source_sha256': runtime.source_sha256,
                      'protocol_compatibility': 'unverified',
                      'can_send_packets': False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
