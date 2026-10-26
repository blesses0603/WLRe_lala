"""StageData:New 的 76-byte 格式適配器；不依賴 GUI、網路或功能模組。"""
import hashlib
import struct
from dataclasses import dataclass
from types import MappingProxyType

PARSER_ID = 'stage-new-76-v1'
PARSER_VERSION = 1
SCHEMA_VERSION = 1
MAX_RECORDS = 20_000
RECORD_SIZE = 76
# 這些範圍原先由舊解析器略過。保留原始來源及 offset，不猜測其語意。
UNINTERPRETED_RANGES = ((2, 2), (10, 11), (32, 20), (56, 1), (63, 13))


class SceneFormatError(ValueError):
    pass


@dataclass(frozen=True)
class SceneTable:
    records: tuple
    source_sha256: str
    source_size: int

    def source_range(self, row_index):
        if type(row_index) is not int or not 0 <= row_index < len(self.records):
            raise IndexError('scene_record_index_out_of_range')
        return 4 + row_index * RECORD_SIZE, RECORD_SIZE


def parse_scene_table(raw):
    """精確長度、筆數及身分檢查；零尺寸場景保留，不宣稱具備導航資料。"""
    if type(raw) is not bytes or not 4 <= len(raw) <= 4 + MAX_RECORDS * RECORD_SIZE:
        raise SceneFormatError('scene_source_size_invalid')
    count, = struct.unpack_from('<i', raw)
    if not 0 <= count <= MAX_RECORDS or len(raw) != 4 + count * RECORD_SIZE:
        raise SceneFormatError('scene_count_or_record_size_invalid')
    records, seen = [], set()
    for index in range(count):
        base = 4 + index * RECORD_SIZE
        def u16(offset, base=base):
            return struct.unpack_from('<H', raw, base + offset)[0]
        scene_id = u16(0)
        if scene_id in seen:
            raise SceneFormatError('duplicate_scene_id')
        seen.add(scene_id)
        row = {
            'id': scene_id, 'name_id': struct.unpack_from('<I', raw, base + 4)[0],
            'model_id': u16(8), 'max_members': raw[base + 21],
            'min_members': raw[base + 23], 'min_level': u16(28),
            'time_minutes': u16(30), 'tag': raw[base + 22],
            'room_capacity': raw[base + 24], 'group': raw[base + 25], 'flag': u16(26),
            'pos_x_ratio': raw[base + 57], 'pos_y_ratio': raw[base + 58],
            'map_width': u16(52), 'map_height': u16(54),
            'small_offset_x': u16(59), 'small_offset_y': u16(61),
        }
        records.append(MappingProxyType(row))
    return SceneTable(tuple(records), hashlib.sha256(raw).hexdigest(), len(raw))
