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
import struct
import sys
import zipfile

try:
    from .lala_manifest_compare import _Libarchive, inspect_archive, MAX_ENTRY_BYTES, CHUNK_SIZE
except ImportError:  # Also allow running directly beside lala_manifest_compare.py.
    from lala_manifest_compare import _Libarchive, inspect_archive, MAX_ENTRY_BYTES, CHUNK_SIZE

MAX_ITEMS = 1_000_000
MAGIC = 0x00594F4F  # 'OOY\x00' as little-endian uint32
FORMAT_VERSION = "2.2.5"


class ParseError(ValueError):
    pass


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


class Reader:
    def __init__(self, data: bytes):
        self.data = memoryview(data)
        self.pos = 0

    def take(self, size: int) -> memoryview:
        if size < 0 or self.pos + size > len(self.data):
            raise ParseError(f"Unexpected end of manifest at offset {self.pos}, wanted {size}")
        value = self.data[self.pos : self.pos + size]
        self.pos += size
        return value

    def unpack(self, fmt: str) -> int:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def u16(self):
        return self.unpack("<H")

    def u32(self):
        return self.unpack("<I")

    def i32(self):
        return self.unpack("<i")

    def i64(self):
        return self.unpack("<q")

    def boolean(self):
        value = self.unpack("<B")
        if value not in (0, 1):
            raise ParseError(f"Invalid boolean at offset {self.pos - 1}: {value}")
        return value == 1

    def utf8(self):
        size = self.u16()
        return self.take(size).tobytes().decode("utf-8", "strict")

    def utf8_list(self):
        return [self.utf8() for _ in range(self.u16())]

    def i32_list(self):
        return [self.i32() for _ in range(self.u16())]


def parse_manifest(data: bytes) -> dict:
    reader = Reader(data)
    if reader.u32() != MAGIC:
        raise ParseError("YooAsset manifest signature mismatch")
    file_version = reader.utf8()
    if file_version != FORMAT_VERSION:
        raise ParseError(f"Unsupported YooAsset manifest format: {file_version}; expected {FORMAT_VERSION}")
    header = {
        "file_version": file_version,
        "enable_addressable": reader.boolean(),
        "location_to_lower": reader.boolean(),
        "include_asset_guid": reader.boolean(),
        "output_name_style": reader.i32(),
        "build_bundle_type": reader.i32(),
        "build_pipeline": reader.utf8(),
        "package_name": reader.utf8(),
        "package_version": reader.utf8(),
        "package_note": reader.utf8(),
    }

    asset_count = reader.i32()
    if not 0 <= asset_count <= MAX_ITEMS:
        raise ParseError(f"Invalid asset count: {asset_count}")
    assets = []
    for _ in range(asset_count):
        assets.append({
            "address": reader.utf8(),
            "path": reader.utf8(),
            "guid": reader.utf8(),
            "tags": reader.utf8_list(),
            "bundle_id": reader.i32(),
        })

    bundle_count = reader.i32()
    if not 0 <= bundle_count <= MAX_ITEMS:
        raise ParseError(f"Invalid bundle count: {bundle_count}")
    bundles = []
    for _ in range(bundle_count):
        bundles.append({
            "name": reader.utf8(),
            "unity_crc": reader.u32(),
            "file_hash": reader.utf8(),
            "file_crc": reader.utf8(),
            "file_size": reader.i64(),
            "encrypted": reader.boolean(),
            "tags": reader.utf8_list(),
            "dependency_ids": reader.i32_list(),
        })

    if reader.pos != len(reader.data):
        raise ParseError(f"Unexpected trailing bytes: {len(reader.data) - reader.pos}")

    names = [bundle["name"] for bundle in bundles]
    if len(set(names)) != len(names):
        raise ParseError("Duplicate bundle names")
    if len(set(asset["path"] for asset in assets)) != len(assets):
        raise ParseError("Duplicate asset paths")
    for bundle in bundles:
        if bundle["file_size"] < 0:
            raise ParseError(f"Negative bundle size for {bundle['name']}")
        if any(dep < 0 or dep >= bundle_count for dep in bundle["dependency_ids"]):
            raise ParseError(f"Invalid dependency ID for bundle {bundle['name']}")
        bundle["dependencies"] = [names[dep] for dep in bundle["dependency_ids"]]
    for asset in assets:
        if asset["bundle_id"] < 0 or asset["bundle_id"] >= bundle_count:
            raise ParseError(f"Invalid asset bundle ID for {asset['path']}")
        asset["bundle_name"] = names[asset["bundle_id"]]

    return {
        "header": header,
        "asset_count": len(assets),
        "bundle_count": len(bundles),
        "assets": assets,
        "bundles": bundles,
    }


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


def bundle_fingerprint(bundle: dict) -> tuple:
    # ID values are local to each version. Compare resolved dependency NAMES.
    return (
        bundle["file_hash"], bundle["file_crc"], bundle["file_size"],
        bundle["unity_crc"], bundle["encrypted"],
        tuple(bundle["tags"]), tuple(bundle["dependencies"]),
    )


def asset_fingerprint(asset: dict) -> tuple:
    return (
        asset["address"], asset["guid"], tuple(asset["tags"]), asset["bundle_name"],
    )


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
