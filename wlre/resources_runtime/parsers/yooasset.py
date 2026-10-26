"""正式共用 YooAsset 2.2.5 解析器；格式版號不是遊戲版號。

移植既有完整 Reader，保留 EOF、引用、重複及邊界檢查。
格式依據：https://github.com/tuyoogame/YooAsset/tree/2.2.10
未知格式／尾段拒絕；不以歷史遊戲版本授予任何功能權限。
"""
import struct

MAX_ITEMS = 1_000_000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAGIC = 0x00594F4F
FORMAT_VERSION = "2.2.5"
PARSER_VERSION = 1


class ParseError(ValueError):
    pass


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
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_MANIFEST_BYTES:
        raise ParseError("Manifest input is empty, oversized or not bytes")
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
    if len({asset["path"] for asset in assets}) != len(assets):
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


