"""Read the official 35-byte Smith table as an unapproved candidate.

The current official SmithData.lua identifies the leading UInt16 as recipeId.
"""
import struct

from wlre.services.world.preview_1275 import parse_smith_1275


def parse_smith_candidate(data):
    """Preserve every row, including multiple recipes for the same item."""
    if type(data) is not bytes or len(data) < 4:
        raise ValueError('Invalid Smith candidate header')
    count = struct.unpack_from('<i', data)[0]
    if not 0 <= count <= 20000 or len(data) != 4 + count * 35:
        raise ValueError('Invalid Smith candidate length or record count')
    result = []
    keys = set()
    for index in range(count):
        pos = 4 + index * 35
        key = struct.unpack_from('<H', data, pos)[0]
        if not key or key in keys:
            raise ValueError('Invalid or duplicate Smith candidate row key')
        keys.add(key)
        parsed = parse_smith_1275(struct.pack('<i', 1) + data[pos + 2:pos + 35])
        row = next(iter(parsed.values()))
        row['order'] = index + 1
        row['recipe_id'] = key
        row['candidate_row_key'] = key
        result.append(row)
    return result


def mark_timed_recipes(rows):
    """Keep time-conditioned rows available for display only."""
    if not isinstance(rows, list) or any(type(row) is not dict or
                                        type(row.get('time_id')) is not int for row in rows):
        raise ValueError('Recipe time condition is missing or invalid')
    return [{**row, 'read_only': row['time_id'] != 0} for row in rows]
