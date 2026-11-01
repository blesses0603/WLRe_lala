"""唯讀比對追蹤中的 1262 資源與 bundled SQLite；絕不刪除檔案。

用法：py -m tools.audit_legacy_1262_database
     py -m tools.audit_legacy_1262_database --database <sqlite3-path>
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from wlre.paths import RESOURCE_ROOT
from wlre.storage.paths import data_root

LEGACY_FILES = (
    "instance_catalog_1262.json",
    "npc_battle_talk_1262.json.gz",
    "npc_event_index_1262.json.gz",
    "npc_interact_1262.json.gz",
    "npc_talk_1262.json.gz",
    "npc_text_1262.json.gz",
)


def audit(database, root=RESOURCE_ROOT):
    database = Path(database)
    result = {"database": str(database), "files": [], "all_identical": False}
    if not database.is_file():
        result["error"] = "database_missing"
        return result
    try:
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
            names = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"bundled_resources", "bundled_active"} <= names:
                result["error"] = "bundled_tables_missing"
                return result
            for name in LEGACY_FILES:
                path = Path(root) / name
                entry = {"name": name, "status": "not_checked"}
                result["files"].append(entry)
                if not path.is_file():
                    entry["status"] = "source_missing"
                    continue
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                entry["source_sha256"] = digest
                active = db.execute(
                    "SELECT sha256 FROM bundled_active WHERE name=?", (name,)
                ).fetchone()
                if not active:
                    entry["status"] = "active_record_missing"
                    continue
                if active[0] != digest:
                    entry["status"] = "active_hash_mismatch"
                    continue
                stored = db.execute(
                    "SELECT data FROM bundled_resources WHERE name=? AND sha256=?",
                    (name, digest)
                ).fetchone()
                if not stored:
                    entry["status"] = "blob_missing"
                elif hashlib.sha256(stored[0]).hexdigest() != digest:
                    entry["status"] = "blob_corrupt"
                elif bytes(stored[0]) != raw:
                    entry["status"] = "content_mismatch"
                else:
                    entry["status"] = "identical"
    except (sqlite3.DatabaseError, OSError) as exc:
        result["error"] = type(exc).__name__
        return result
    result["all_identical"] = all(
        row["status"] == "identical" for row in result["files"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=(
        data_root() / "official_sync" / "derived_catalogs" /
        "resource_inventory.sqlite3"))
    args = parser.parse_args()
    report = audit(args.database)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
