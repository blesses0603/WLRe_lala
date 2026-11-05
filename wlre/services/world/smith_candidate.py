"""Read the official 35-byte Smith table as an unapproved candidate.

The current official SmithData.lua identifies the leading UInt16 as recipeId.
"""

from wlre.services.parser_diagnostics import diagnosed, checkpoint
import struct

from wlre.services.world.preview_1275 import parse_smith_1275


@diagnosed('smith-35-v1')
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
        checkpoint(offset=pos, field='recipe', record=index + 1)
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


@diagnosed('smith-reviewed-v1')
def parse_smith_records(data):
    """Select the reviewed 33/35-byte layout, preserving every recipe row."""
    if type(data) is not bytes or len(data) < 4:
        raise ValueError('Invalid Smith table header')
    count=struct.unpack_from('<i',data)[0]
    if not 0 <= count <= 20000:
        raise ValueError('Invalid Smith table count')
    if len(data)==4+count*33:
        checkpoint(profile='smith-33-v1')
        rows=list(parse_smith_1275(data).values())
    elif len(data)==4+count*35:
        checkpoint(profile='smith-35-v1')
        rows=parse_smith_candidate(data)
    else:
        raise ValueError('Unknown Smith table layout')
    return mark_timed_recipes(rows)
