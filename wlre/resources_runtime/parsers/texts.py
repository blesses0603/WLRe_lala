"""TextData_C v1：UInt32 ID、UInt16 byte 長度及 UTF-16 LE；保留來源位移。"""
import hashlib
import struct
from dataclasses import dataclass
from types import MappingProxyType

PARSER_ID = 'text-data-v1'
PARSER_VERSION = 1
SCHEMA_VERSION = 1
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 1_000_000


class TextFormatError(ValueError):
    pass


@dataclass(frozen=True)
class TextTable:
    records: tuple
    source_sha256: str
    source_size: int
    offsets: tuple

    def source_range(self, row_index):
        if type(row_index) is not int or not 0 <= row_index < len(self.offsets):
            raise IndexError('text_record_index_out_of_range')
        return self.offsets[row_index]


def parse_text_table(raw):
    if type(raw) is not bytes or not 4 < len(raw) <= MAX_SOURCE_BYTES:
        raise TextFormatError('text_source_size_invalid')
    count, = struct.unpack_from('<i', raw)
    if not 1 <= count <= min(MAX_RECORDS, (len(raw) - 4) // 6):
        raise TextFormatError('text_record_count_invalid')
    records, offsets, seen = [], [], set()
    position = 4
    for _ in range(count):
        if position + 6 > len(raw):
            raise TextFormatError('text_record_header_truncated')
        key, size = struct.unpack_from('<IH', raw, position)
        end = position + 6 + size
        if size % 2 or end > len(raw):
            raise TextFormatError('text_record_length_invalid')
        if key in seen:
            raise TextFormatError('duplicate_text_id')
        try:
            value = raw[position + 6:end].decode('utf-16-le')
        except UnicodeDecodeError:
            raise TextFormatError('text_encoding_invalid') from None
        seen.add(key)
        records.append(MappingProxyType({'id': key, 'text': value}))
        offsets.append((position, end - position))
        position = end
    if position != len(raw):
        raise TextFormatError('text_source_trailing_bytes')
    return TextTable(tuple(records), hashlib.sha256(raw).hexdigest(), len(raw), tuple(offsets))
