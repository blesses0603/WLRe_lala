import copy
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile

from tools.navigation.official_cache import CacheError, compare, decode_cache, decode_extra, extract


def binary():
    # One tile, one triangle, two separately serialized vertex arrays, one node.
    values = [1, 1, 0, 0, 1, 1, 3, 0, 1, 2,
              3, 0, 0, 0, 0, 0, 1000, 1000, 0, 0,
              3, 0, 0, 0, 0, 0, 1000, 1000, 0, 0,
              1, 0, 524289, 0, 1, 2]
    return struct.pack('<' + str(len(values)) + 'i', *values)


def cache(extra=None, additional=None):
    stream = BytesIO()
    with ZipFile(stream, 'w') as z:
        z.writestr('meta.json', b'{"version":4.3.60,"graphs":1,"typeNames":["Pathfinding.RecastGraph"]}')
        z.writestr('graph0.json', json.dumps({'useTiles': False}))
        z.writestr('graph0_extra.binary', binary() if extra is None else extra)
        for name in ('graph0_references.binary', 'graph_references.binary', 'node_link2.binary'):
            z.writestr(name, struct.pack('<i', 0))
        if additional:
            z.writestr(*additional)
    return stream.getvalue()


class OfficialCache(unittest.TestCase):
    def test_exact_consumption_preserves_both_vertices_and_node_metadata(self):
        result = decode_cache(cache())
        mesh = result['mesh']
        self.assertEqual(mesh['bytes_consumed'], len(binary()))
        self.assertEqual(mesh['tiles'][0]['node_metadata'], [[0, 524289]])
        self.assertFalse(result['coordinate_frame_verified'])
        self.assertFalse(result['serialized_connections_decoded'])
        self.assertFalse(result['can_send_packets'])

    def test_truncation_trailing_bytes_and_node_index_disagreement_fail(self):
        bad = bytearray(binary())
        struct.pack_into('<i', bad, len(bad) - 4, 1)
        for raw in (binary()[:-1], binary() + b'\x00', bytes(bad)):
            with self.subTest(raw=raw[-8:]):
                with self.assertRaises(CacheError): decode_extra(raw)

    def test_unknown_entries_and_multitile_layout_are_not_guessed(self):
        with self.assertRaises(CacheError): decode_cache(cache(additional=('other', b'x')))
        raw = bytearray(binary())
        struct.pack_into('<i', raw, 0, 2)
        with self.assertRaises(CacheError): decode_extra(raw)

    def test_geometric_match_does_not_authorize_live_movement(self):
        official = decode_cache(cache())
        tile = official['mesh']['tiles'][0]
        candidate = {'kind': 'offline_recast_candidate', 'resource_revision': 1275,
                     'can_send_packets': False, 'vertices': [[v / 1000 for v in p] for p in tile['vertices_a_int3']],
                     'triangles': copy.deepcopy(tile['triangles'])}
        result = compare(candidate, official)
        self.assertTrue(result['vertex_sets']['vertices_a_int3']['same_triangle_geometry_mm'])
        self.assertFalse(result['official_runtime_graph_captured'])
        self.assertFalse(result['can_send_packets'])
        candidate['vertices'][0][1] = 1
        self.assertFalse(compare(candidate, official)['vertex_sets']['vertices_a_int3']['same_triangle_geometry_mm'])


class RealOfficialCache(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('LALA_1275_CURRENT_SCENE_ZIP') and os.environ.get('LALA_1275_SCENES_ZIP')
                         and os.environ.get('LALA_1275_SELECT_JSON'), 'Requires all fourteen official sources')
    def test_official_sources_package_and_load_without_candidates(self):
        from wlre.services.world.official_navigation import package, load_archive
        from wlre.services.world.navigation import Repository
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, changed = root/'current', root/'changed'
            extract(os.environ['LALA_1275_CURRENT_SCENE_ZIP'], None, current)
            extract(os.environ['LALA_1275_SCENES_ZIP'], os.environ['LALA_1275_SELECT_JSON'], changed)
            archive = package([current, changed], root/'official.zip')
            decoded = load_archive(archive)
            self.assertEqual(len(decoded), 14)
            self.assertEqual(sum(len(row['mesh']['tiles'][0]['triangles']) for row in decoded.values()), 3650)
            repository = Repository(archive)
            self.assertEqual(repository.source_revision, 1275)
            self.assertEqual(len(repository.load(12170).faces), 214)
            self.assertTrue(all(row['source_kind']=='official_astar_startup_cache' for row in repository.catalog))

    @unittest.skipUnless(os.environ.get('LALA_1275_CURRENT_SCENE_ZIP'), 'Requires current official scene sources and UnityPy')
    def test_current_cache_is_resolved_from_the_actual_astar_reference(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'official'
            result = extract(os.environ['LALA_1275_CURRENT_SCENE_ZIP'], None, output)
            self.assertEqual(len(result['scenes']), 1)
            row = result['scenes'][0]
            self.assertEqual(row['official_faces'], 214)
            self.assertEqual(row['settings_differences'], {})
            decoded = json.loads((output / '12170_official_decoded.json').read_text())
            self.assertEqual(decoded['source']['text_asset_path_id'], -5371349077274317333)
            self.assertEqual(len(decoded['mesh']['tiles'][0]['vertices_a_int3']), 129)
            # Historical decoded data is an independent layout regression only;
            # it is never used to supply or authorize the 1275 graph.
            with ZipFile('wlre/resources/navigation_data.zip') as z:
                historical = json.loads(z.read('decoded/M12170_graph0.json'))
            self.assertEqual(decoded['mesh'], historical)
            self.assertFalse(result['official_runtime_graph_captured'])

    @unittest.skipUnless(os.environ.get('LALA_1275_SCENES_ZIP') and os.environ.get('LALA_1275_SELECT_JSON'),
                         'Requires original thirteen scene sources and UnityPy')
    def test_all_thirteen_references_resolve_and_decode_to_eof(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'official'
            result = extract(os.environ['LALA_1275_SCENES_ZIP'], os.environ['LALA_1275_SELECT_JSON'], output)
            self.assertEqual(len(result['scenes']), 13)
            self.assertTrue(all(row['official_faces'] > 0 for row in result['scenes']))
            self.assertTrue(all(not row['settings_differences'] for row in result['scenes']))
            self.assertFalse(result['can_send_packets'])
