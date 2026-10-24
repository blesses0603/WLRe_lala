"""1275 scene Recast collision input inventory and fail-closed regressions."""
import os
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from tools.resources.audit_1275_scene_collision import (
    Recast1275Error, class_inventory, inspect)


class CollisionSource1275Tests(unittest.TestCase):
    def test_corrupted_or_short_serialized_file_does_not_create_mesh(self):
        with self.assertRaises(Recast1275Error):
            class_inventory(b'')
        with self.assertRaises(Recast1275Error):
            class_inventory(b'\0' * 80)

    def test_invalid_or_incomplete_selection_never_produces_mesh(self):
        import json
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            selection = path / 'selection.json'
            archive = path / 'empty.zip'
            selection.write_text(json.dumps({
                'target_revision': 1275, 'bundles': [],
            }), encoding='utf8')
            with ZipFile(archive, 'w') as z:
                z.writestr('inventory.json', '{}')
            with self.assertRaises(Recast1275Error):
                inspect(archive, selection)

    @unittest.skipUnless(os.environ.get('LALA_1275_SCENES_ZIP')
                         and os.environ.get('LALA_1275_SELECT_JSON'),
                         'Local source archives not supplied to CI')
    def test_real_1275_all_thirteen_scene_collision_inputs(self):
        result = inspect(
            Path(os.environ['LALA_1275_SCENES_ZIP']),
            Path(os.environ['LALA_1275_SELECT_JSON']))
        self.assertEqual(result['resource_revision'], 1275)
        self.assertEqual(result['scene_count'], 13)
        self.assertEqual(result['bundle_count'], 26)
        self.assertEqual(result['unity_object_count'], 2277)
        self.assertEqual(result['class_totals']['Mesh'], 35)
        self.assertEqual(result['class_totals']['TerrainData'], 10)
        self.assertEqual(result['class_totals']['MeshCollider'], 3)
        self.assertEqual(result['class_totals']['BoxCollider'], 3)
        self.assertEqual(result['class_totals']['Terrain'], 10)
        self.assertEqual(result['class_totals']['ParticleSystem'], 35)
        self.assertTrue(result['terrain_or_collider_inputs_found'])
        self.assertFalse(result['rasterizer_layers_verified'])
        self.assertFalse(result['walkable_triangle_mesh_built'])
        self.assertFalse(result['can_send_packets'])


if __name__ == '__main__':
    unittest.main()


class MetadataBoundaries(unittest.TestCase):
    @staticmethod
    def asset(*,count=1,duplicate=False):
        import struct
        meta=bytearray(b'2021.3.45f1\0'+struct.pack('<iBi',19,1,1))
        meta.extend(struct.pack('<iBh',43,0,-1)+b'\0'*16+struct.pack('<iii',0,0,0))
        meta.extend(struct.pack('<i',count))
        for i in range(count):
            meta.extend(b'\0'*(-len(meta)%4))
            meta.extend(struct.pack('<qqIi',1 if duplicate else i+1,0,4,0))
        offset=(48+len(meta)+15)//16*16
        header=bytearray(48);struct.pack_into('>I',header,8,22)
        struct.pack_into('>IQQ',header,20,len(meta),offset+4,offset)
        return bytes(header)+bytes(meta)+b'\0'*(offset-48-len(meta))+b'mesh'
    def test_valid_object_inventory_and_mono_filter(self):
        from tools.resources.extract_1275_recast_settings import mono_behaviours
        self.assertEqual(class_inventory(self.asset()),{43:1})
        self.assertEqual(mono_behaviours(self.asset()),[])
    def test_object_table_may_not_read_into_payload(self):
        import struct
        raw=bytearray(self.asset());struct.pack_into('>I',raw,20,55)
        with self.assertRaises(Recast1275Error):class_inventory(raw)
    def test_duplicate_path_ids_are_rejected(self):
        with self.assertRaises(Recast1275Error):class_inventory(self.asset(count=2,duplicate=True))
    def test_wrong_metadata_endianness_is_rejected(self):
        raw=bytearray(self.asset());raw[16]=1
        with self.assertRaises(Recast1275Error):class_inventory(raw)
