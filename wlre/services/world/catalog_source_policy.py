"""五類靜態資料的統一來源策略；不改變遊戲協定或授權。

1275 正式遊戲資料只接受獨立驗證的 active_runtime()；
官方 SQLite 驗證資料不可直接授權遊戲協定或封包。
1262 內建資源只供歷史、測試或明確舊版路徑使用。
"""
from dataclasses import dataclass


FEATURES = frozenset(("npc", "items", "maps", "crafting", "expedition"))


@dataclass(frozen=True)
class CatalogSource:
    feature: str
    revision: str
    kind: str
    authoritative: bool
    gameplay_allowed: bool


def source_for(feature, *, revision=None):
    """提供一致的資料來源決策；正式 Runtime 不可降級到 1262。"""
    if feature not in FEATURES:
        raise ValueError("不支援的靜態資料功能")
    from wlre.services.world.runtime_1275 import baseline_revision
    current = baseline_revision() if revision is None else revision
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    dynamic = current_runtime()
    if dynamic is not None and str(dynamic.revision) == current:
        return CatalogSource(feature, current, "verified_dynamic_runtime", True, False)
    if current not in ("1275", "1262"):
        raise ValueError("官方動態 Runtime 尚未完成驗證")
    if current == "1275":
        return CatalogSource(feature, current, "verified_1275_runtime", True, True)
    if current == "1262":
        return CatalogSource(feature, current, "bundled_1262_legacy", False, False)
    raise ValueError("不支援的資料版本")


def official_runtime(feature):
    """要求完整的官方 1275 Runtime，絕不讀取 SQLite 候選代替。"""
    policy = source_for(feature)
    if policy.kind not in ("verified_1275_runtime", "verified_dynamic_runtime"):
        raise ValueError("此版本不可使用 1275 正式遊戲資料")
    from wlre.services.world.runtime_1275 import active_runtime
    runtime = active_runtime()
    if str(getattr(runtime, "revision", None)) != policy.revision:
        raise ValueError("官方 Runtime 與資料來源版本不一致")
    return runtime


def verified_runtime_for_official(feature, remote):
    """Bridge official version-pair identity to a verified gameplay runtime.

    An independently validated, release-pinned runtime is required. A newer
    official resource download alone is NOT an executable gameplay runtime.
    """
    if feature not in FEATURES:
        raise ValueError('不支援的靜態資料功能')
    from wlre.services.world.catalog_runtime import official_package_versions
    from wlre.services.resource_compatibility import load_supported_resources
    official_package_versions(remote)
    pinned = load_supported_resources()
    if remote['official_exe_version'] != pinned['official_game_exe_version']:
        raise ValueError('官方客戶端版本尚未完成協定驗證')
    from wlre.services.world.dynamic_bundle_runtime import activate_for_official
    return activate_for_official(remote)


def is_official_revision(revision):
    """Classify tags for safe UI routing only; never establish provenance."""
    return (type(revision) in (int, str) and str(revision).isdecimal()
            and 1275 <= int(revision) <= 999999)
