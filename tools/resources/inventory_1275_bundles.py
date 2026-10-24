"""Audit official installed 1275 YooAsset bundles without modifying the game.

The local owner runs this against their own installation.  By default only
inventory metadata is written.  Full files are copied only with --archive.
No network operations, automatic upload, or source-data commits are performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

PACKAGES = ("DataPackage", "MainPackage")
REVISION = "1275"
MAX_FILES = 300000


class InventoryError(ValueError):
    """The supplied installation is missing or not the expected revision."""


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_files(root: Path, package: str):
    folder = root / package / "ManifestFiles"
    if not folder.is_dir() or folder.is_symlink():
        raise InventoryError(package + " 找不到 ManifestFiles")
    files = sorted(folder.glob(package + "_" + REVISION + "_*.bytes"))
    if len(files) != 1 or not files[0].is_file() or files[0].is_symlink():
        raise InventoryError(package + " 必須有唯一的 1275 Manifest .bytes")
    prefix = files[0].with_suffix("")
    hash_path = prefix.with_suffix(".hash")
    if not hash_path.is_file() or hash_path.is_symlink():
        raise InventoryError(package + " 缺少同名 .hash")
    return (files[0], hash_path)


def inventory(root: Path):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise InventoryError("遊戲 YooAsset 根目錄無效")
    rows = []
    for package in PACKAGES:
        manifest, hashfile = _manifest_files(root, package)
        folder = root / package / "BundleFiles"
        if not folder.is_dir() or folder.is_symlink():
            raise InventoryError(package + " 找不到 BundleFiles")
        candidates = [(manifest, "manifest"), (hashfile, "manifest_hash")]
        candidates.extend((p, "bundle") for p in folder.rglob("__data"))
        for path, kind in candidates:
            if path.is_symlink() or not path.is_file():
                raise InventoryError("拒絕符號連結或異常遊戲檔案：" + str(path))
            if len(rows) >= MAX_FILES:
                raise InventoryError("資源數量超出安全上限")
            rows.append({
                "package": package,
                "kind": kind,
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": _digest(path),
            })
    return {"revision": REVISION, "source": "local-game-installation",
            "file_count": len(rows),
            "bundle_count": sum(v["kind"] == "bundle" for v in rows),
            "files": rows}


def _selected_records(report, selection_file, group=None):
    """Match a proposed extraction list to verified on-disk SHA-256 metadata."""
    with Path(selection_file).open(encoding="utf-8") as stream:
        selection = json.load(stream)
    if (not isinstance(selection, dict)
            or selection.get("target_revision") != 1275
            or not isinstance(selection.get("bundles"), list)):
        raise InventoryError("1275 差異清單格式／版本無效")
    originals = {row["path"]: row for row in report["files"]}
    manifest_hashes = selection.get("manifest_sha256_1275")
    if not isinstance(manifest_hashes, dict):
        raise InventoryError("差異清單缺少 1275 Manifest 指紋")
    for package in PACKAGES:
        official = [row for row in report["files"]
                    if row["package"] == package and row["kind"] == "manifest"]
        if (len(official) != 1
                or official[0]["sha256"] != manifest_hashes.get(package)):
            raise InventoryError(package + " 的 Manifest 不符合差異清單")
    chosen, seen = [], set()
    for expected in selection["bundles"]:
        if not isinstance(expected, dict):
            raise InventoryError("差異清單包含異常項目")
        selected_group = expected.get("group")
        if selected_group not in ("data", "scenes", "ui", "other"):
            raise InventoryError("差異清單分類無效")
        if group is not None and group != selected_group:
            continue
        path = expected.get("path")
        if not isinstance(path, str) or path in seen:
            raise InventoryError("差異清單包含重複或錯誤路徑")
        seen.add(path)
        actual = originals.get(path)
        if (actual is None or actual["kind"] != "bundle"
                or actual["package"] != expected.get("package")
                or actual["size"] != expected.get("size")
                or actual["sha256"] != expected.get("sha256")
                or path.split("/")[-2] != expected.get("file_hash")):
            raise InventoryError("1275 Bundle 與差異清單不符：" + path)
        chosen.append(actual)
    if not chosen:
        raise InventoryError("差異清單在指定分類中沒有可歸檔的 Bundle")
    return chosen


def _collect_split(yoo_root, output, selection_file, group, split_mib):
    """Collect all selected 1275 bundles in size-capped independent ZIP parts.

    A part is a complete ZIP with a verified inventory and both official
    manifests, not a binary split needing an external merge program.
    """
    if type(split_mib) is not int or not 1 <= split_mib <= 2048:
        raise InventoryError("--split-mib 必須是 1 到 2048 的整數")
    root = Path(yoo_root).resolve(strict=True)
    target = Path(output).resolve()
    if target == root or root in target.parents:
        raise InventoryError("輸出不得寫入官方遊戲安裝目錄")
    if target.suffix.lower() != ".zip":
        raise InventoryError("分卷輸出檔名必須以 .zip 結尾")
    report = inventory(root)  # Hash every local file once, before export.
    selected = _selected_records(report, selection_file, group)
    metadata = [row for row in report["files"] if row["kind"] != "bundle"]
    inventory_json = json.dumps(report, ensure_ascii=False, indent=2)
    # Allow room for ZIP headers, manifest of the part, and future extensions.
    overhead = (len(inventory_json.encode("utf-8"))
                + sum(row["size"] for row in metadata) + 128 * 1024)
    limit = split_mib * 1024 * 1024
    if overhead >= limit:
        raise InventoryError("單卷容量小於清單與官方 Manifest 所需容量")
    chunks, current, current_size = [], [], overhead
    for row in selected:
        if row["size"] + overhead > limit:
            raise InventoryError("單一 Bundle 超過分卷上限：" + row["path"])
        if current and current_size + row["size"] > limit:
            chunks.append(current)
            current, current_size = [], overhead
        current.append(row)
        current_size += row["size"]
    if current:
        chunks.append(current)
    paths = [target.with_name(f"{target.stem}.part{i:02d}.zip")
             for i in range(1, len(chunks) + 1)]
    for path in paths:
        if path.exists():
            raise FileExistsError("分卷已存在，拒絕覆寫：" + str(path))
    created = []
    try:
        for i, (path, bundles) in enumerate(zip(paths, chunks), 1):
            with ZipFile(path, "x", compression=ZIP_STORED, allowZip64=True) as archive:
                created.append(path)
                archive.writestr("inventory.json", inventory_json)
                archive.writestr("selection_part.json", json.dumps({
                    "revision": REVISION, "part": i,
                    "part_count": len(chunks),
                    "selected_bundle_count": len(bundles),
                    "paths": [row["path"] for row in bundles],
                }, ensure_ascii=False, indent=2))
                for row in (*metadata, *bundles):
                    archive.write(root / row["path"], "source/" + row["path"])
            # Detect a source file changing between inventory and ZIP write.
            # No archive is reported successful unless its bytes match pins.
            with ZipFile(path) as archive:
                for row in bundles:
                    digest = hashlib.sha256()
                    member = "source/" + row["path"]
                    if archive.getinfo(member).file_size != row["size"]:
                        raise InventoryError("分卷檔案大小不符合1275清單：" + row["path"])
                    with archive.open(member) as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                    if digest.hexdigest() != row["sha256"]:
                        raise InventoryError("分卷SHA-256與來源清單不符：" + row["path"])
            if path.stat().st_size > limit:
                raise InventoryError("ZIP 分卷超出 --split-mib 上限：" + str(path))
    except Exception:
        for created_path in created:
            created_path.unlink(missing_ok=True)
        raise
    return {"revision": REVISION, "bundles": report["bundle_count"],
            "selected_bundles": len(selected), "parts": [
                {"output": str(path), "selected_bundles": len(rows),
                 "bytes": path.stat().st_size}
                for path, rows in zip(paths, chunks)],
            "included_bundle_bytes": True}


def collect(yoo_root, output, *, include_bundles=False, selection_file=None,
            group=None, split_mib=None):

    if split_mib is not None:
        if include_bundles or selection_file is None:
            raise InventoryError("--split-mib 僅能與 --select 一起使用")
        return _collect_split(yoo_root, output, selection_file, group, split_mib)
    root = Path(yoo_root).resolve(strict=True)
    target = Path(output).resolve()
    if target == root or root in target.parents:
        raise InventoryError("輸出不得寫入官方遊戲安裝目錄")
    if target.exists():
        raise FileExistsError("輸出檔已存在，拒絕覆寫：" + str(target))
    report = inventory(root)
    if include_bundles and selection_file is not None:
        raise InventoryError("--archive 及 --select 不可同時使用")
    if group is not None and selection_file is None:
        raise InventoryError("指定 --group 必須同時提供 --select")
    if selection_file is not None:
        selected = _selected_records(report, selection_file, group)
        records = [row for row in report["files"] if row["kind"] != "bundle"]
        records.extend(selected)
    else:
        records = report["files"] if include_bundles else [
            row for row in report["files"] if row["kind"] != "bundle"
        ]
    # Always include a complete bundle inventory; copy bytes only on opt-in.
    with ZipFile(target, "x", compression=ZIP_STORED, allowZip64=True) as archive:
        archive.writestr("inventory.json",
                         json.dumps(report, ensure_ascii=False, indent=2))
        for row in records:
            archive.write(root / row["path"], "source/" + row["path"])
    selected_bundles = sum(row["kind"] == "bundle" for row in records)
    return {"output": str(target), "bundles": report["bundle_count"],
            "selected_bundles": selected_bundles,
            "included_bundle_bytes": selected_bundles > 0,
            "files_in_archive": len(records) + 1}


def main(argv=None):
    p = argparse.ArgumentParser(description="1275 本機 YooAsset 安全清點（唯讀原始安裝）")
    p.add_argument("yoo_root", type=Path,
                   help="遊戲資料夾的 yoo 路徑（包含 MainPackage／DataPackage）")
    p.add_argument("--output", type=Path, default=Path("lala_1275_local_inventory.zip"))
    p.add_argument("--archive", action="store_true",
                   help="額外打包所有 BundleFiles/__data，體積可能很大")
    p.add_argument("--select", type=Path,
                   help="只歸檔已分析的1262→1275差異Bundle JSON清單")
    p.add_argument("--group", choices=("data", "scenes", "ui", "other"),
                   help="搭配 --select 僅歸檔指定分類；不指定則提取全部差異")
    p.add_argument("--split-mib", type=int,
                   help="搭配 --select 自動分卷，每個完整ZIP最大容量（MiB）；建議256")
    args = p.parse_args(argv)
    print(json.dumps(collect(args.yoo_root, args.output,
                             include_bundles=args.archive,
                             selection_file=args.select, group=args.group,
                             split_mib=args.split_mib),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
