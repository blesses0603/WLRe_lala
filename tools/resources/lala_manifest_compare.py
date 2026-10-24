#!/usr/bin/env python3
"""Read-only comparison of YooAsset manifest archive snapshots (ZIP / RAR5).

This does NOT decode YooAsset .bytes or extract/publish game resources.
RAR support uses the system's libarchive shared library.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import zipfile
import zlib

MAX_ENTRIES = 1000
MAX_ENTRY_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
RELEASE_RE = re.compile(r"^(DataPackage|MainPackage)_(\d+)(?:_|\.)")


@dataclass(frozen=True)
class Member:
    name: str
    size: int
    sha256: str
    hex_value: str | None = None
    crc32_le: str | None = None


def _stream_digest(read_chunks, declared_size: int, show_small_hex: bool) -> tuple[int, str, str | None, str]:
    if declared_size > MAX_ENTRY_BYTES:
        raise ValueError(f"Member exceeds {MAX_ENTRY_BYTES} bytes")
    h = hashlib.sha256()
    count = 0
    crc = 0
    small = bytearray()
    for chunk in read_chunks:
        if not chunk:
            continue
        count += len(chunk)
        if count > MAX_ENTRY_BYTES:
            raise ValueError("Member exceeded streaming size limit")
        h.update(chunk)
        crc = zlib.crc32(chunk, crc)
        if show_small_hex and len(small) <= 16:
            small.extend(chunk[: 17 - len(small)])
    if declared_size >= 0 and count != declared_size:
        raise ValueError(f"Size mismatch: expected {declared_size}, received {count}")
    return count, h.hexdigest(), small.hex() if show_small_hex and count <= 16 else None, crc.to_bytes(4, "little").hex()


def _zip_members(path: Path) -> list[Member]:
    output = []
    total = 0
    with zipfile.ZipFile(path) as archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        if len(entries) > MAX_ENTRIES:
            raise ValueError("Too many files in archive")
        for entry in entries:
            total += entry.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Archive exceeds uncompressed size limit")
            with archive.open(entry, "r") as handle:
                def chunks():
                    while True:
                        data = handle.read(CHUNK_SIZE)
                        if not data:
                            break
                        yield data
                size, sha, tiny, crc = _stream_digest(chunks(), entry.file_size, entry.filename.endswith(".hash"))
            output.append(Member(entry.filename, size, sha, tiny, crc))
    return output


class _Libarchive:
    def __init__(self) -> None:
        location = ctypes.util.find_library("archive")
        if not location:
            raise RuntimeError("RAR5 comparison requires libarchive (libarchive.so)")
        lib = ctypes.CDLL(location)
        lib.archive_read_new.restype = ctypes.c_void_p
        lib.archive_read_support_filter_all.argtypes = [ctypes.c_void_p]
        lib.archive_read_support_format_all.argtypes = [ctypes.c_void_p]
        lib.archive_read_open_filename.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.archive_read_next_header.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        lib.archive_entry_pathname.argtypes = [ctypes.c_void_p]
        lib.archive_entry_pathname.restype = ctypes.c_char_p
        lib.archive_entry_size.argtypes = [ctypes.c_void_p]
        lib.archive_entry_size.restype = ctypes.c_int64
        lib.archive_read_data.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        lib.archive_read_data.restype = ctypes.c_ssize_t
        lib.archive_error_string.argtypes = [ctypes.c_void_p]
        lib.archive_error_string.restype = ctypes.c_char_p
        lib.archive_read_free.argtypes = [ctypes.c_void_p]
        self.lib = lib

    def error(self, reader) -> str:
        message = self.lib.archive_error_string(reader)
        return message.decode("utf-8", "replace") if message else "unknown libarchive error"


def _rar_members(path: Path) -> list[Member]:
    binding = _Libarchive()
    lib = binding.lib
    reader = lib.archive_read_new()
    if not reader:
        raise RuntimeError("Unable to initialize libarchive")
    try:
        lib.archive_read_support_filter_all(reader)
        lib.archive_read_support_format_all(reader)
        if lib.archive_read_open_filename(reader, os.fsencode(path), 10240) < 0:
            raise RuntimeError(binding.error(reader))
        members = []
        total = 0
        buffer = ctypes.create_string_buffer(CHUNK_SIZE)
        while True:
            entry_ptr = ctypes.c_void_p()
            status = lib.archive_read_next_header(reader, ctypes.byref(entry_ptr))
            if status == 1:  # ARCHIVE_EOF
                break
            if status < 0:
                raise RuntimeError(f"RAR header error: {binding.error(reader)}")
            name_bytes = lib.archive_entry_pathname(entry_ptr) or b""
            name = os.fsdecode(name_bytes)
            if name.endswith("/"):
                continue
            if len(members) >= MAX_ENTRIES:
                raise ValueError("Too many files in archive")
            size_hint = lib.archive_entry_size(entry_ptr)
            if size_hint > MAX_ENTRY_BYTES:
                raise ValueError("RAR member exceeds size limit")

            def chunks():
                while True:
                    size = lib.archive_read_data(reader, buffer, CHUNK_SIZE)
                    if size < 0:
                        raise RuntimeError(f"RAR data error: {binding.error(reader)}")
                    if size == 0:
                        break
                    yield buffer.raw[:size]

            size, sha, tiny, crc = _stream_digest(chunks(), size_hint, name.endswith(".hash"))
            total += size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Archive exceeds uncompressed size limit")
            members.append(Member(name, size, sha, tiny, crc))
        return members
    finally:
        lib.archive_read_free(reader)


def inspect_archive(path: Path, expected_package: str) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as stream:
        signature = stream.read(8)
    if signature.startswith(b"PK\x03\x04"):
        archive_format = "zip"
        members = _zip_members(path)
    elif signature.startswith(b"Rar!\x1a\x07"):
        archive_format = "rar"
        members = _rar_members(path)
    else:
        raise ValueError(f"Unsupported archive signature: {path.name}")

    interesting = [m for m in members if m.name.lower().endswith((".bytes", ".hash"))]
    role_members = {"manifest": [m for m in interesting if m.name.lower().endswith(".bytes")],
                    "hash": [m for m in interesting if m.name.lower().endswith(".hash")]}
    if len(role_members["manifest"]) != 1 or len(role_members["hash"]) != 1:
        raise ValueError(f"Expected exactly one .bytes and one .hash in {path.name}")
    manifest = role_members["manifest"][0]
    hash_file = role_members["hash"][0]
    try:
        hash_text = bytes.fromhex(hash_file.hex_value or "").decode("ascii")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Invalid text in .hash for {path.name}") from exc
    if not re.fullmatch(r"[0-9a-fA-F]{8}", hash_text):
        raise ValueError(f"Unexpected 8-character .hash format in {path.name}")
    manifest_crc_valid = hash_text.lower() == manifest.crc32_le
    match = RELEASE_RE.match(Path(manifest.name).name)
    if not match or match.group(1) != expected_package:
        raise ValueError(f"Manifest name does not match {expected_package}: {manifest.name}")
    return {
        "input_file": path.name,
        "archive_format": archive_format,
        "package": expected_package,
        "version_from_manifest_filename": match.group(2),
        "manifest_name": Path(manifest.name).name,
        "members": [asdict(item) for item in interesting],
        "hash_text": hash_text,
        "manifest_crc32_le": manifest.crc32_le,
        "manifest_crc_valid": manifest_crc_valid,
        "total_file_count": len(members),
        "note": "Version is inferred from filename; internal YooAsset binary fields not decoded",
    }


def compare(old: dict, new: dict) -> dict:
    def by_suffix(record: dict, suffix: str) -> dict:
        return next(member for member in record["members"] if member["name"].lower().endswith(suffix))

    old_m, new_m = by_suffix(old, ".bytes"), by_suffix(new, ".bytes")
    old_h, new_h = by_suffix(old, ".hash"), by_suffix(new, ".hash")
    return {
        "package": old["package"],
        "old_version": old["version_from_manifest_filename"],
        "new_version": new["version_from_manifest_filename"],
        "manifest_changed": old_m["sha256"] != new_m["sha256"],
        "hash_file_changed": old_h["sha256"] != new_h["sha256"],
        "old_manifest_bytes": old_m["size"],
        "new_manifest_bytes": new_m["size"],
        "old_manifest_sha256": old_m["sha256"],
        "new_manifest_sha256": new_m["sha256"],
        "old_hash_hex": old_h["hex_value"],
        "new_hash_hex": new_h["hex_value"],
        "old_hash_value": old["hash_text"],
        "new_hash_value": new["hash_text"],
        "old_crc_verified": old["manifest_crc_valid"],
        "new_crc_verified": new["manifest_crc_valid"],
    }


def markdown_report(payload: dict) -> str:
    lines = [
        "# LaLa 1262 → 1275 manifest 基準比較（第一階段）", "",
        f"產生時間：{payload['generated_at']}（UTC）", "",
        "## 比對結果", "",
        "| 項目 | 1262 | 1275 | 判定 |", "| --- | --- | --- | --- |",
    ]
    for diff in payload["comparisons"]:
        changed = "已變更" if diff["manifest_changed"] else "未變更"
        lines.append(f"| {diff['package']} manifest 版本 | {diff['old_version']} | {diff['new_version']} | {changed} |")
        lines.append(f"| {diff['package']} manifest 大小 | {diff['old_manifest_bytes']:,} B | {diff['new_manifest_bytes']:,} B | {'有差異' if diff['old_manifest_bytes'] != diff['new_manifest_bytes'] else '相同'} |")
        lines.append(f"| {diff['package']} .hash | `{diff['old_hash_value']}` | `{diff['new_hash_value']}` | {'有差異' if diff['hash_file_changed'] else '相同'} |")
        lines.append(f"| {diff['package']} CRC32 驗證 | {'通過' if diff['old_crc_verified'] else '失敗'} | {'通過' if diff['new_crc_verified'] else '失敗'} | {'通過' if diff['old_crc_verified'] and diff['new_crc_verified'] else '注意'} |")
    lines.extend([
        "", "## 已確認與尚未確認", "",
        "- ✅ 檔案層級：已比對每個 ZIP／RAR manifest 的檔案名稱、解壓後長度、SHA-256、8-byte `.hash`，並檢驗 YooAsset 的 CRC32（小端序十六進位）。",
        "- ✅ 可用同一程式重跑相同來源，並輸出機器可讀 JSON。",
        "- ⚠️ 尚未解碼 YooAsset `.bytes` 的內部 Bundle 對照表，**不能**據此宣稱已完成資源細項差異、地圖或導航重建。",
        "- ⚠️ 官方 DataVer 與兩個 `.version` 的即時端點值未包含在本次離線分析；檔名中的 1262／1275 不等於線上即時查證。",
        "- ⚠️ 尚未提供 LaLa 專案工作樹，無法整合登入版本防護、CI、PR 及 PC／Android 程式。",
        "- ⚠️ PR #52 公開資源風險需另行檢查；本工具不抽出原始 Bundle，不會上傳原始資源至 GitHub。",
        "", "## 下一步", "",
        "1. 加入 YooAsset manifest 格式解析，才可列出每個 bundle 的新增／修改／刪除。",
        "2. 對接官方 DataVer → DataPackage.version / MainPackage.version 三步檢查。",
        "3. 取得 LaLa 程式工作樹，將這個比較器整合為單一更新入口並建置回歸測試。",
        "4. 補齊 1275 `12910` 的 Mesh 來源，單獨完成導航網格驗證。",
        "", "## SHA-256（manifest .bytes）", "",
    ])
    for diff in payload["comparisons"]:
        lines.extend([
            f"- {diff['package']} 舊版：`{diff['old_manifest_sha256']}`",
            f"- {diff['package']} 新版：`{diff['new_manifest_sha256']}`",
        ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("old-data", "old-main", "new-data", "new-main"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--report", type=Path, help="Write Markdown report")
    parser.add_argument("--json", type=Path, help="Write JSON machine-readable record")
    args = parser.parse_args(argv)

    old_data = inspect_archive(args.old_data, "DataPackage")
    new_data = inspect_archive(args.new_data, "DataPackage")
    old_main = inspect_archive(args.old_main, "MainPackage")
    new_main = inspect_archive(args.new_main, "MainPackage")
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshots": [old_data, old_main, new_data, new_main],
        "comparisons": [compare(old_data, new_data), compare(old_main, new_main)],
        "scope": "archive entry and hash comparison only; YooAsset contents not decoded",
    }
    report = markdown_report(payload)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.report:
        print(report)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, zipfile.BadZipFile) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(2)
