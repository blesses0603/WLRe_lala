"""Browse the embedded, source-verified 1262 dungeon and co-op catalog.

Static records never imply that a server has an open room or that a reward
is claimable. No packet is emitted by this module.
"""
import json
from functools import lru_cache

from wlre.paths import RESOURCE_ROOT

CATALOG_FILE = RESOURCE_ROOT / "instance_catalog_1262.json"


@lru_cache(maxsize=1)
def official_catalog():
    value = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    records = value.get("records")
    counts = value.get("counts", {})
    if value.get("version") != 1262 or not value.get("verified_source"):
        raise ValueError("未經 1262 官方驗證的副本資料表")
    if not isinstance(records, list) or len(records) != 30:
        raise ValueError("副本資料筆數不符")
    if counts.get("dungeon_records") != len(records):
        raise ValueError("副本資料紀錄數不符")
    if (sum(row["kind"] == 1 for row in records),
        sum(row["kind"] == 2 for row in records),
        sum(row["kind"] == 3 for row in records)) != (26, 3, 1):
        raise ValueError("副本種類筆數不符")
    seen = set()
    for row in records:
        key = (row["id"], row["variant"])
        if key in seen or not isinstance(row.get("name"), str) or not row["name"].strip():
            raise ValueError("副本重複或缺少官方中文名稱")
        seen.add(key)
        if not isinstance(row.get("awards"), list) or len(row["awards"]) > 16:
            raise ValueError("副本獎勵資料不完整")
        if any(len(award) != 4 or not (1 <= award[0] <= 16)
               for award in row["awards"]):
            raise ValueError("副本獎勵欄位異常")
    return value


def entries_for(mode):
    if mode not in ("main", "coop"):
        raise ValueError("未知副本分類")
    rows = official_catalog()["records"]
    return tuple(row for row in rows if (row["kind"] == 2) == (mode == "coop"))
