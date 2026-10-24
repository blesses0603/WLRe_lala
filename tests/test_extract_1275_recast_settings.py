"""Synthetic and opt-in real official 1275 AstarPath parsing tests."""
import base64
import io
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from tools.resources.extract_1275_recast_settings import (
    Recast1275Error, parse_astar_blob, _decompress, extract)


def make_blob(*, type_name='Pathfinding.RecastGraph', files=None):
    memory = io.BytesIO()
    with ZipFile(memory, 'w') as z:
        z.writestr('graph0.json', json.dumps({'name':'Recast Graph','cellSize':0.1,
                                            'rasterizeColliders':True}))
        z.writestr('meta.json', ('{"version": 4.3.60, "graphs": 1, '
                '"typeNames": ["%s"]}' % type_name))
        for key, value in (files or {}).items():
            z.writestr(key, value)
    encoded=base64.b64encode(memory.getvalue())
    return b'\x00'*36+struct.pack('<I',len(encoded))+encoded+b'\x00'*6


class Recast1275Tests(unittest.TestCase):
    def test_graph_settings_are_not_precomputed_navmesh(self):
        result=parse_astar_blob(make_blob())
        self.assertEqual(result['graph_type'],'Pathfinding.RecastGraph')
        self.assertEqual(result['serialized_version'],'4.3.60')
        self.assertTrue(result['settings']['rasterizeColliders'])
        self.assertFalse(result['has_serialized_walkable_mesh'])

    def test_unknown_graph_type_and_missing_nodes_rejected(self):
        with self.assertRaises(Recast1275Error):
            parse_astar_blob(make_blob(type_name='Pathfinding.GridGraph'))
        with self.assertRaises(Recast1275Error):
            parse_astar_blob(make_blob(files={'nodes.bin':b'fake'}))
        self.assertIsNone(parse_astar_blob(b'not-a-zipped-astar-record'))
        with self.assertRaises(Recast1275Error):
            parse_astar_blob(b'\x00'*36+struct.pack('<I',999999)+b'UEsDB')

    def test_not_a_graph_does_not_fake_navmesh(self):
        self.assertEqual(_decompress(b'hello',0,5),b'hello')
        with self.assertRaises(Recast1275Error):
            _decompress(b'no',0,5)

    @unittest.skipUnless(os.getenv('LALA_1275_SCENES_ZIP') and
                         os.getenv('LALA_1275_SELECT_JSON'),
                         'Real 1275 scene sources not provided')
    def test_real_1275_thirteen_scene_asts_are_configuration_only(self):
        result=extract(Path(os.environ['LALA_1275_SCENES_ZIP']),
                       Path(os.environ['LALA_1275_SELECT_JSON']))
        self.assertEqual(result['scene_count'],13)
        self.assertFalse(result['navmesh_verified'])
        self.assertFalse(result['can_send_packets'])
        self.assertEqual({row['model_id'] for row in result['scenes']},
                         {12910,*range(13216,13228)})
        for scene in result['scenes']:
            self.assertEqual(scene['graph_type'],'Pathfinding.RecastGraph')
            self.assertFalse(scene['has_serialized_walkable_mesh'])


if __name__=='__main__':
    unittest.main()


class UnityFSVersions(unittest.TestCase):
    @staticmethod
    def bundle(version):
        payload=b'geometry-test'
        info=b'\0'*16+struct.pack('>I',1)+struct.pack('>IIH',len(payload),len(payload),0)
        info+=struct.pack('>IQQI',1,0,len(payload),0)+b'CAB-test\0'
        prefix=b'UnityFS\0'+struct.pack('>I',version)+b'5.x.x\0'+b'2021.3.45f2\0'
        header=prefix+struct.pack('>QIII',0,len(info),len(info),0x40)
        if version>=7:header+=b'\0'*(-len(header)%16)
        raw=bytearray(header+info+payload)
        struct.pack_into('>Q',raw,len(prefix),len(raw))
        return bytes(raw)
    def test_v6_and_v8_header_alignment(self):
        from tools.resources.extract_1275_recast_settings import unity_nodes
        for version in (6,8):
            with self.subTest(version=version):self.assertEqual(unity_nodes(self.bundle(version)),[('CAB-test',b'geometry-test')])
    def test_unknown_unityfs_version_is_rejected(self):
        from tools.resources.extract_1275_recast_settings import unity_nodes
        with self.assertRaises(Recast1275Error):unity_nodes(self.bundle(9))
