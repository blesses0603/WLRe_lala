"""五類靜態資料的統一來源策略；不改變遊戲協定或授權。

1275 正式遊戲資料只接受獨立驗證的 active_runtime()；
SQLite candidate_rows 和自動候選索引只供唯讀預覽，不得升格。
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
    if current == "1275":
        return CatalogSource(feature, current, "verified_1275_runtime", True, True)
    if current == "1262":
        return CatalogSource(feature, current, "bundled_1262_legacy", False, False)
    raise ValueError("不支援的資料版本")


def official_runtime(feature):
    """要求完整的官方 1275 Runtime，絕不讀取 SQLite 候選代替。"""
    policy = source_for(feature)
    if policy.kind != "verified_1275_runtime":
        raise ValueError("此版本不可使用 1275 正式遊戲資料")
    from wlre.services.world.runtime_1275 import active_runtime
    runtime = active_runtime()
    if getattr(runtime, "revision", None) != 1275:
        raise ValueError("官方 Runtime 與資料來源版本不一致")
    return runtime
