"""Version-pair-aware, read-only runtime catalog metadata for current official assets.

The live official version pair is authoritative; historical 1275 constants are
not used. Parsed record counts are sourced from verified TextAssets stored by
the official catalog pipeline, never inferred from a Manifest asset count.
This does not grant gameplay or network protocol approval.
"""
from __future__ import annotations

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


def parse_runtime_recipes(raw, items):
    """Recognize reviewed 33/35-byte layouts; preserve every recipe identity.

    The legacy product-keyed UI cannot choose between several recipe IDs.
    Ambiguous products remain in recipe_catalog and are excluded from that UI.
    Dynamic recipes stay read-only pending separate protocol validation.
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
        checked.append({**row, 'open_used': item['open_used'], 'read_only': True})
    return {r['item_id']: r for r in checked if counts[r['item_id']] == 1}, checked


def prepare_dynamic_runtime(*, sync=False, sync_root=None, observe=None,
                            retrieve=None, execute=None,
                            max_download_bytes=32 * 1024 * 1024,
                            max_downloads=24):
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
        _PORTAL_TABLES, _OPTIONAL_ROUTE_TABLES)
    observe = observe_official_versions if observe is None else observe
    retrieve = fetch_official_manifest if retrieve is None else retrieve
    execute = execute_update_plan if execute is None else execute
    root = Path(sync_root) if sync_root is not None else data_root() / 'official_sync'
    if (type(sync) is not bool or type(max_downloads) is not int
            or not 0 <= max_downloads <= 24 or type(max_download_bytes) is not int
            or not 0 <= max_download_bytes <= 32 * 1024 * 1024):
        raise DynamicRuntimeUnavailable('Invalid runtime download budget')
    before = validate_snapshot(observe())
    manifests = {p: retrieve(spec_from_snapshot(before, p), cache_root=root / 'manifests')
                 for p in PACKAGES}
    identity = identity_from_verified_manifests(before, manifests)
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
        for table in _PORTAL_TABLES + _OPTIONAL_ROUTE_TABLES:
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
