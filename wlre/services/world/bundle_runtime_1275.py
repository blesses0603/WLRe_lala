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
_ASSET_ROOT = 'Assets/ResourcesBuild/Data/'


class BundleRuntimeUnavailable(ValueError):
    """A complete audited 1275 runtime could not be constructed safely."""


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
    try:
        for table in _REQUIRED_TABLES:
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

        eve = sources['Eve']
        if hashlib.sha256(eve).hexdigest() != EVE_SHA256:
            raise BundleRuntimeUnavailable('1275 Eve 來源 SHA-256 不符')
        npc = json.loads(derive_eve_index(eve, 'EventData.NewNpc'))
        interacts = json.loads(derive_eve_index(eve, 'EventData.NewInteract'))
        if (npc.get('record_count') != 10975
                or interacts.get('record_count') != 1634
                or len(npc.get('scenes', {})) != 1262):
            raise BundleRuntimeUnavailable('NPC／互動事件數不符合已審核 1275 資料')
        items = parse_itemdata(sources['ItemData_C'])
        talk_rows = parse_talk_data(sources['TalkData_C'])
        texts = parse_text_data(sources['TextData_C'])
        recipes = parse_smith_1275(sources['SmithData_C'])
        scene_rows = parse_stages(sources['ScenesData_C'])
        doors = parse_doors_1275(eve)
        if len(recipes) != 1032 or any(
                ident not in items or type(items[ident].get('open_used')) is not int
                for ident in recipes):
            raise BundleRuntimeUnavailable('1275 製作配方與物品開放狀態未完成交叉驗證')
        if not scene_rows or not talk_rows or not texts:
            raise BundleRuntimeUnavailable('1275 場景或對話原始資料缺失')

        # Expedition is a real service catalog, not just a candidate label.
        # This is the same independently audited 1275 source identity that
        # the older full-ZIP loader validates before expedition dispatch.
        if (hashlib.sha256(sources['AdventureData_C']).hexdigest()
                != ADVENTURE_1275_SHA256 or
                hashlib.sha256(sources['AdventureLvData_C']).hexdigest()
                != ADVENTURE_LEVEL_1275_SHA256):
            raise BundleRuntimeUnavailable('1275 遠征任務／等級來源 SHA-256 不符')
        expedition = parse_expedition(
            sources['AdventureData_C'], sources['AdventureLvData_C'])
        expedition_npcs = parse_expedition_npcs(
            sources['NpcData_C'], sources['NpcCareerData_C'])
        if (len(expedition['tasks']) != 260
                or len(expedition['levels']) != 10
                or len(expedition_npcs) != 7561):
            raise BundleRuntimeUnavailable('1275 遠征任務／夥伴資料筆數不符')
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

        return Preview1275(
            npc_index=PreviewNPCIndex(npc),
            interact_index=PreviewInteractIndex(interacts),
            items=items,
            talks={int(k): v['text'] for k, v in talk_rows.items()},
            texts=texts,
            recipes=recipes,
            scene_ids=frozenset(scene_rows),
            doors=doors, expedition=expedition,
        )
    except BundleRuntimeUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise BundleRuntimeUnavailable(
            '官方 Bundle 的資料格式無法建立完整 1275 Runtime') from exc
