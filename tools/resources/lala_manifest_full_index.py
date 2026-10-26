#!/usr/bin/env python3
"""Full YooAsset 2.2.5 manifest index and version-to-version difference report.

Based on the original YooAsset 2.2.10 reader, which uses manifest format 2.2.5:
https://github.com/tuyoogame/YooAsset/tree/2.2.10

Reads archive entries in memory; never extracts game content to a directory.
The generated full indexes contain game asset paths; keep them private.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import ctypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import zipfile

try:
    from .lala_manifest_compare import _Libarchive, inspect_archive, MAX_ENTRY_BYTES, CHUNK_SIZE
except ImportError:  # Also allow running directly beside lala_manifest_compare.py.
    from lala_manifest_compare import _Libarchive, inspect_archive, MAX_ENTRY_BYTES, CHUNK_SIZE

# 保留直接腳本與既有 import API；執行期解析器不反向依賴工具套件。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wlre.resources_runtime.parsers.yooasset import (  # noqa: E402
    FORMAT_VERSION as FORMAT_VERSION,
    MAGIC as MAGIC,
    MAX_ITEMS as MAX_ITEMS,
    ParseError as ParseError,
    Reader as Reader,
    parse_manifest as parse_manifest,
    bundle_fingerprint as bundle_fingerprint,
    asset_fingerprint as asset_fingerprint,
)


def validate_private_output(output_dir: Path) -> Path:
    """Prevent accidentally checking full copyrighted asset indexes into Git."""
    target = output_dir.expanduser().resolve()
    for directory in (target, *target.parents):
        if (directory / ".git").exists():
            raise ParseError(
                "Refusing to save full indexes inside a Git worktree. "
                "Use an external private output directory (for example /tmp/lala-index)."
            )
    return target


def manifest_bytes_from_archive(path: Path, entry_name: str) -> bytes:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            entry = archive.getinfo(entry_name)
            if entry.file_size > MAX_ENTRY_BYTES:
                raise ParseError("Manifest is too large")
            with archive.open(entry) as stream:
                data = stream.read(MAX_ENTRY_BYTES + 1)
            if len(data) != entry.file_size:
                raise ParseError("ZIP manifest size does not match archive header")
            return data

    binding = _Libarchive()
    lib = binding.lib
    reader = lib.archive_read_new()
    if not reader:
        raise ParseError("Unable to initialize RAR reader")
    try:
        lib.archive_read_support_filter_all(reader)
        lib.archive_read_support_format_all(reader)
        if lib.archive_read_open_filename(reader, str(path).encode(), 10240) < 0:
            raise ParseError(binding.error(reader))
        buffer = ctypes.create_string_buffer(CHUNK_SIZE)
        while True:
            entry_ptr = ctypes.c_void_p()
            status = lib.archive_read_next_header(reader, ctypes.byref(entry_ptr))
            if status == 1:
                break
            if status < 0:
                raise ParseError(binding.error(reader))
            name = (lib.archive_entry_pathname(entry_ptr) or b"").decode("utf-8", "replace")
            if name != entry_name:
                continue
            declared_size = lib.archive_entry_size(entry_ptr)
            if declared_size > MAX_ENTRY_BYTES:
                raise ParseError("RAR manifest is too large")
            chunks = []
            total = 0
            while True:
                got = lib.archive_read_data(reader, buffer, CHUNK_SIZE)
                if got < 0:
                    raise ParseError(binding.error(reader))
                if got == 0:
                    break
                total += got
                if total > MAX_ENTRY_BYTES:
                    raise ParseError("RAR manifest exceeds safe limit")
                chunks.append(buffer.raw[:got])
            if total != declared_size:
                raise ParseError("RAR manifest size does not match archive header")
            return b"".join(chunks)
        raise ParseError(f"Cannot find {entry_name} in archive")
    finally:
        lib.archive_read_free(reader)


def load_index(path: Path, package_name: str) -> dict:
    overview = inspect_archive(path, package_name)
    if not overview["manifest_crc_valid"]:
        raise ParseError(f"Manifest CRC32 mismatch in {path.name}")
    manifest_name = next(m["name"] for m in overview["members"] if m["name"].endswith(".bytes"))
    blob = manifest_bytes_from_archive(path, manifest_name)
    expected = next(m["sha256"] for m in overview["members"] if m["name"] == manifest_name)
    if hashlib.sha256(blob).hexdigest() != expected:
        raise ParseError(f"Manifest hash mismatch while reading {path.name}")
    index = parse_manifest(blob)
    if index["header"]["package_name"] != package_name:
        raise ParseError(f"Internal package name mismatch in {path.name}")
    expected_manifest_name = f"{package_name}_{index['header']['package_version']}.bytes"
    if Path(manifest_name).name != expected_manifest_name:
        raise ParseError(f"Filename and embedded package version disagree in {path.name}")
    index["source"] = {
        "archive": path.name,
        "manifest_name": manifest_name,
        "manifest_sha256": expected,
        "manifest_hash": overview["hash_text"],
    }
    return index


def diff_records(old: dict, new: dict, kind: str) -> dict:
    if kind == "bundle":
        old_rows, new_rows = old["bundles"], new["bundles"]
        key, fp = "name", bundle_fingerprint
    elif kind == "asset":
        old_rows, new_rows = old["assets"], new["assets"]
        key, fp = "path", asset_fingerprint
    else:
        raise ValueError(kind)
    old_map = {row[key]: row for row in old_rows}
    new_map = {row[key]: row for row in new_rows}
    added = sorted(new_map.keys() - old_map.keys())
    removed = sorted(old_map.keys() - new_map.keys())
    common = old_map.keys() & new_map.keys()
    changed = sorted(k for k in common if fp(old_map[k]) != fp(new_map[k]))
    return {
        "old_count": len(old_map), "new_count": len(new_map),
        "added_count": len(added), "removed_count": len(removed),
        "modified_count": len(changed), "unchanged_count": len(common) - len(changed),
        "added": added, "removed": removed, "modified": changed,
    }


def dependency_impact(new: dict, bundle_diff: dict) -> dict:
    """Count direct/indirect impact without pretending asset metadata changed."""
    changed = set(bundle_diff["added"] + bundle_diff["modified"])
    reverse = defaultdict(set)
    for bundle in new["bundles"]:
        for dependency in bundle["dependencies"]:
            reverse[dependency].add(bundle["name"])
    impacted = set(changed)
    work = deque(changed)
    while work:
        for dependent in reverse[work.popleft()]:
            if dependent not in impacted:
                impacted.add(dependent)
                work.append(dependent)
    direct_assets = [asset["path"] for asset in new["assets"] if asset["bundle_name"] in changed]
    potentially_affected = [asset["path"] for asset in new["assets"] if asset["bundle_name"] in impacted]
    return {
        "changed_bundle_count": len(changed),
        "dependency_affected_bundle_count": len(impacted),
        "direct_asset_count": len(direct_assets),
        "possibly_affected_asset_count": len(potentially_affected),
        "direct_asset_paths": sorted(direct_assets),
    }


def report_text(result: dict) -> str:
    lines = ["# LaLa 1262 → 1275 YooAsset Manifest 全量索引差異", "",
             f"產生時間：{result['generated_at']} (UTC)", "",
             "來源為使用者提供的四份 Manifest 壓縮檔，未使用線上即時版本。", "",
             "## 全量解析驗證", "",
             "| Package | 1262 Assets | 1275 Assets | 1262 Bundles | 1275 Bundles |", "| --- | ---: | ---: | ---: | ---: |"]
    for package, entry in result["packages"].items():
        old, new = entry["old"], entry["new"]
        lines.append(f"| {package} | {old['asset_count']:,} | {new['asset_count']:,} | {old['bundle_count']:,} | {new['bundle_count']:,} |")
    lines.extend(["", "## 差異統計", "",
                  "| Package / 類別 | 新增 | 修改 | 刪除 | 未變更 |", "| --- | ---: | ---: | ---: | ---: |"])
    for package, entry in result["packages"].items():
        for kind in ("bundles", "assets"):
            diff = entry[kind]
            lines.append(f"| {package} / {kind} | {diff['added_count']:,} | {diff['modified_count']:,} | {diff['removed_count']:,} | {diff['unchanged_count']:,} |")
    lines.extend(["", "## 變更影響範圍（估算）", "",
                  "| Package | 變更 Bundle | 含相依傳遞的 Bundle | 直接對應 Asset | 含相依的潛在受影響 Asset |",
                  "| --- | ---: | ---: | ---: | ---: |"])
    for package, entry in result["packages"].items():
        impact = entry["impact"]
        lines.append(f"| {package} | {impact['changed_bundle_count']:,} | {impact['dependency_affected_bundle_count']:,} | {impact['direct_asset_count']:,} | {impact['possibly_affected_asset_count']:,} |")
    scene_related = []
    for entry in result["packages"].values():
        for field in ("added", "modified", "removed"):
            scene_related.extend(name for name in entry["bundles"][field] if "12910" in name.lower())
    if scene_related:
        lines.extend(["", "## 1275 地圖 12910 導航追蹤", "",
                      "以下 Bundle 出現在本次異動集合（**只表示 Bundle 差異，不表示已取得 Mesh**）：", ""])
        lines.extend(f"- `{name}`" for name in sorted(set(scene_related)))
        lines.extend(["", "仍需查明 `unity default resources` 中所需 Mesh 的合法來源；Manifest 索引本身不能提供原始頂點與三角形。", ""])
    lines.extend(["", "## 解讀與限制", "",
                  "- ✅ 所有 Asset / Bundle 紀錄依 YooAsset 2.2.5 格式完整讀取，檢查完整檔案消耗、索引範圍與無重複名稱。",
                  "- ✅ 比對解析後的 Bundle Hash、大小、CRC、標籤及相依 Bundle 名稱，而非直接比較易變動的內部 BundleID。",
                  "- ✅ 另追蹤依賴受影響 Bundle 的其他 Bundle 和 Asset；這是風險範圍估算，不能視為所有這些 Asset 都確實改變內容。",
                  "- ⚠️ Bundle 名稱、AssetPath 及 Hash 均屬索引資訊。尚未解包 Bundle 原始內容，不能推論具體 NPC 欄位或導航 Mesh。",
                  "- ⚠️ 本報告和完整 JSON 索引應僅在私人環境保存，不應直接提交至公開 GitHub。",
                  "- ⚠️ 官方 DataVer 與 LaLa 程式相容性尚未驗證；此結果不等於 LaLa 已完成 1275 支援。", ""])
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("old-data", "old-main", "new-data", "new-main"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args(argv)
    sources = {
        "DataPackage": (args.old_data, args.new_data),
        "MainPackage": (args.old_main, args.new_main),
    }
    result = {"schema_version": 1,
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "packages": {}}
    args.output_dir = validate_private_output(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for package, (old_path, new_path) in sources.items():
        old = load_index(old_path, package)
        new = load_index(new_path, package)
        for label, index in (("1262", old), ("1275", new)):
            (args.output_dir / f"{package}_{label}_full_index.json").write_text(
                json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["packages"][package] = {
            "old": {"asset_count": old["asset_count"], "bundle_count": old["bundle_count"], "header": old["header"], "source": old["source"]},
            "new": {"asset_count": new["asset_count"], "bundle_count": new["bundle_count"], "header": new["header"], "source": new["source"]},
            "bundles": diff_records(old, new, "bundle"),
            "assets": diff_records(old, new, "asset"),
        }
        result["packages"][package]["impact"] = dependency_impact(new, result["packages"][package]["bundles"])
    (args.output_dir / "difference.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "difference.md").write_text(report_text(result), encoding="utf-8")
    print(report_text(result))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(2)
