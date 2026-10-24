"""Stage-only 1275 route planning and strict official binary source regressions."""
import struct
import unittest

from wlre.services.world.topology_1275 import (
    Topology1275Error, parse_stage_markers, parse_binary_links, parse_eve_links,
    build_topology, read_only_route, packet_to_world_xz, world_to_packet_xy)


def stage(scene):
    return {'id':scene, 'pos_x_ratio':2, 'pos_y_ratio':4,
            'offset_y': 3400, 'is_open': scene != 13216}


def fixture():
    stages={sid:stage(sid) for sid in (10000,12050,12051,13216)}
    markers=struct.pack('<i',1)+struct.pack(
        '<HBHIHHIB',10000,2,0,42,100,200,777,1)
    links=struct.pack('<i',1)+struct.pack(
        '<HHHHHH',12050,200,300,12051,600,700)
    eve=('［事件ID］' if False else
         '[事件ID]=10000\n'
         ' 原場景位置[X:100,Y:200] 目標場景:[12050],位置[X:1,Y:2]\n'
         '[事件ID]=13216\n'
         ' 原場景位置[X:33,Y:44] 目標場景:[12050],位置[X:1,Y:2]\n'
         ).encode('utf-16')
    return stages, markers, links, eve


class Topology1275Tests(unittest.TestCase):
    def test_verified_links_are_read_only_and_scale_stage_positions(self):
        stages, markers, binary, eve=fixture()
        result=build_topology(stages,markers,binary,eve)
        self.assertEqual(result['source_revision'],1275)
        self.assertEqual(result['counts'],{
            'stages':4,'markers':1,'binary_links':1,'eve_links':2})
        self.assertEqual(result['markers'][10000][0]['scaled_xy'],[200,800])
        self.assertEqual(result['binary_links'][12050][0]['destination_scaled_xy'],
                         [1200,2800])
        self.assertFalse(result['can_send_packets'])
        self.assertFalse(result['navmesh_verified'])
        self.assertFalse(result['eve_links'][10000][0]['can_send_packets'])

    def test_stage_link_route_never_authorizes_navigation(self):
        result=build_topology(*fixture())
        plan=read_only_route(result,10000,12051)
        self.assertEqual(plan['stages'],[10000,12050,12051])
        self.assertTrue(plan['found'])
        self.assertFalse(plan['can_send_packets'])
        self.assertFalse(plan['navmesh_verified'])
        with self.assertRaises(Topology1275Error):
            read_only_route(result,10000,13216)
        self.assertFalse(read_only_route(result,12051,10000)['found'])

    def test_source_truncation_invalid_utf16_and_unknown_lines_fail(self):
        stages, markers, binary, eve=fixture()
        for source,func in (
            (markers[:-1],lambda raw: parse_stage_markers(raw,stages)),
            (binary[:-1],lambda raw: parse_binary_links(raw,stages)),
            (b'\xff',lambda raw: parse_eve_links(raw,stages)),
            ('garbage'.encode('utf-16'),
             lambda raw: parse_eve_links(raw,stages)),
        ):
            with self.subTest(data=source[:12]),self.assertRaises(
                    (Topology1275Error,UnicodeError)):
                func(source)

    def test_packet_world_is_source_formula_not_graph_origin(self):
        s=stage(10000)
        x,z=packet_to_world_xz(s,1000,1500)
        self.assertAlmostEqual(x,10)
        self.assertAlmostEqual(z,19)
        p,q=world_to_packet_xy(s,x,z)
        self.assertAlmostEqual(p,1000)
        self.assertAlmostEqual(q,1500)
        with self.assertRaises(Topology1275Error):
            packet_to_world_xz(s,-1,0)


if __name__ == '__main__':
    unittest.main()
