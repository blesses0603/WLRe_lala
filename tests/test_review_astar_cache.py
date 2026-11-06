"""Synthetic malformed inputs for the offline navigation research decoder."""
import hashlib
import io
import json
import struct
import unittest
import zipfile
from unittest.mock import patch
from tools import review_astar_cache as subject


def geometry():
    pack = lambda *v: struct.pack('<' + 'i' * len(v), *v)
    vertices = pack(3, 0, 0, 0, 1000, 0, 0, 0, 0, 1000)
    return pack(1, 1, 0, 0, 1, 1, 3, 0, 1, 2) + vertices * 2 + pack(1, 0, 1, 0, 1, 2)


def archive(**overrides):
    settings = dict(guid={'value': 'synthetic'}, rotation=dict(x=0, y=0, z=0),
                    forcedBoundsCenter=dict(x=1, y=1, z=1),
                    forcedBoundsSize=dict(x=2, y=2, z=2))
    parts = dict.fromkeys(subject.MEMBERS, b'')
    parts.update({'graph0.json': json.dumps(settings).encode(),
                  'meta.json': b'{"version":4.3.60,"graphs":1,"guids":["synthetic"],"typeNames":["Pathfinding.RecastGraph"]}',
                  'graph0_extra.binary': geometry(), 'node_link2.binary': bytes(4)})
    parts.update(overrides)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as output:
        for name, data in parts.items():
            output.writestr(name, data)
    return stream.getvalue()


class ReviewTests(unittest.TestCase):
    def review(self, raw):
        with patch.object(subject, 'REVIEWED_CACHES', {hashlib.sha256(raw).hexdigest()}):
            return subject.review_cache(raw)

    def test_geometry_roundtrip_and_no_movement_authority(self):
        result = self.review(archive())
        self.assertEqual(result['origin'], [0, 0, 0])
        self.assertEqual(result['mesh']['tiles'][0]['triangles'], [[0, 1, 2]])
        self.assertFalse(result['can_send_packets'])
        self.assertFalse(result['references_interpreted'])
        self.assertFalse(result['live_movement_verified'])

    def test_unknown_fingerprint(self):
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            subject.review_cache(archive())

    def test_truncation_and_trailing_bytes(self):
        for raw in (geometry()[:-1], geometry() + b'\0'):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                subject.decode_geometry(raw)

    def test_tile_and_count_limits(self):
        for offset, value in ((0, 2), (24, -1), (24, 100001), (24, 2)):
            raw = bytearray(geometry())
            struct.pack_into('<i', raw, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                subject.decode_geometry(raw)

    def test_node_references(self):
        raw = geometry()[:-4] + struct.pack('<i', 99)
        with self.assertRaisesRegex(ValueError, 'references'):
            subject.decode_geometry(raw)

    def test_unknown_version_and_links(self):
        for changed in ({'meta.json': b'{"version":4.3.61,}'}, {'node_link2.binary': b'\1\0\0\0'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.review(archive(**changed))

    def test_archive_schema_and_quota(self):
        with self.assertRaisesRegex(ValueError, 'member'):
            self.review(archive(extra=b''))
        with patch.object(subject, 'MAX_BYTES', 1), self.assertRaises(ValueError):
            self.review(archive())

    def test_invalid_archive(self):
        with self.assertRaisesRegex(ValueError, 'archive'):
            self.review(b'not a zip')


if __name__ == '__main__':
    unittest.main()
