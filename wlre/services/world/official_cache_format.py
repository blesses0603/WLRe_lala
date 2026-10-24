"""Bounded read-only decoder for official Astar 4.3.60 single-tile caches.

Vertex arrays and node flags are preserved without assigning runtime semantics.
"""
import hashlib
from io import BytesIO
import json
import re
import struct
from zipfile import ZipFile


class CacheError(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Reader:
    def __init__(self, raw):
        if len(raw) > 64 * 1024 * 1024:
            raise CacheError('Graph exceeds the supported budget')
        self.raw = raw
        self.pos = 0

    def ints(self, count, unsigned=False):
        if count < 0 or self.pos + count * 4 > len(self.raw):
            raise CacheError('Truncated graph data')
        result = struct.unpack_from('<' + str(count) + ('I' if unsigned else 'i'), self.raw, self.pos)
        self.pos += count * 4
        return list(result)

    def count(self, limit):
        n = self.ints(1)[0]
        if not 0 <= n <= limit:
            raise CacheError('Graph count outside the supported budget')
        return n


def decode_extra(raw):
    r = Reader(raw)
    grid = r.ints(2)
    if grid != [1, 1]:
        raise CacheError('Only the reviewed single-tile 4.3.60 layout is supported')
    x, z, width, depth = r.ints(4)
    if [x, z, width, depth] != [0, 0, 1, 1]:
        raise CacheError('Unexpected tile coordinates')
    indices = r.ints(r.count(6_000_000))
    if len(indices) % 3:
        raise CacheError('Triangle index count must be divisible by three')
    arrays = []
    for _ in range(2):
        values = r.ints(r.count(2_000_000) * 3)
        arrays.append([values[i:i+3] for i in range(0, len(values), 3)])
    if len(arrays[0]) != len(arrays[1]):
        raise CacheError('Vertex set lengths differ')
    triangles = [indices[i:i+3] for i in range(0, len(indices), 3)]
    if any(len(set(t)) != 3 or any(not 0 <= v < len(arrays[0]) for v in t) for t in triangles):
        raise CacheError('Invalid triangle indices')
    if r.count(2_000_000) != len(triangles):
        raise CacheError('Triangle/node count mismatch')
    metadata = []
    for tri in triangles:
        metadata.append(r.ints(2, unsigned=True))
        if r.ints(3) != tri:
            raise CacheError('Node indices do not match tile triangle indices')
    if r.pos != len(raw):
        raise CacheError('Unconsumed graph bytes')
    return {'tile_grid': grid, 'tiles': [{'x': x, 'z': z, 'width': width, 'depth': depth,
            'vertices_a_int3': arrays[0], 'vertices_b_int3': arrays[1],
            'triangles': triangles, 'node_metadata': metadata}], 'bytes_consumed': r.pos}


def decode_cache(raw):
    if len(raw) > 16 * 1024 * 1024:
        raise CacheError('Cache ZIP exceeds the supported budget')
    with ZipFile(BytesIO(raw)) as z:
        names = z.namelist()
        expected = {'meta.json', 'graph0.json', 'graph0_extra.binary',
                    'graph0_references.binary', 'graph_references.binary', 'node_link2.binary'}
        if len(names) != len(set(names)) or set(names) != expected:
            raise CacheError('Unexpected cache ZIP entries')
        if sum(i.file_size for i in z.infolist()) > 64 * 1024 * 1024:
            raise CacheError('Expanded cache exceeds the supported budget')
        if z.testzip() is not None:
            raise CacheError('Cache ZIP CRC mismatch')
        meta = json.loads(re.sub(rb'("version"\s*:\s*)(\d+\.\d+\.\d+)', rb'\1"\2"', z.read('meta.json')))
        if (meta.get('version') != '4.3.60' or meta.get('graphs') != 1
                or meta.get('typeNames') != ['Pathfinding.RecastGraph']):
            raise CacheError('Unsupported cache graph type or version')
        graph = json.loads(z.read('graph0.json'))
        if graph.get('useTiles') is not False:
            raise CacheError('Tiled graphs are not supported')
        return {'meta': meta, 'settings': graph, 'mesh': decode_extra(z.read('graph0_extra.binary')),
                'members': {name: {'bytes': len(z.read(name)), 'sha256': sha(z.read(name))} for name in names},
                'cache_sha256': sha(raw), 'coordinate_frame_verified': False,
                'serialized_connections_decoded': False, 'can_send_packets': False}
