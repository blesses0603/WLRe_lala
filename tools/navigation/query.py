"""Read-only route inspection of an offline candidate, using world metres."""
import argparse
import json
from pathlib import Path
from tools.navigation.scan import ScanError,to_offline_mesh,validate


def route(candidate,start,end,start_height=None,end_height=None):
    if (candidate.get('kind')!='offline_recast_candidate'
            or candidate.get('can_send_packets') is not False):
        raise ScanError('Expected a non-executable offline candidate')
    if candidate.get('triangles'):
        validate({'coordinate_space':'unity_world_y_up','vertices':candidate['vertices'],
                  'triangles':candidate['triangles']},candidate['settings'])
    mesh=to_offline_mesh(candidate)
    result=mesh.route([v*1000 for v in start],[v*1000 for v in end],
        None if start_height is None else start_height*1000,
        None if end_height is None else end_height*1000)
    return {'points_unity_world':[[v/1000 for v in point] for point in result['points']],
            'length_metres':result['length']/1000,'can_send_packets':False,
            'coordinate_mapping_verified':False,'dynamic_obstacles_applied':False}


def main():
    p=argparse.ArgumentParser(description='Query offline world-space routes; never send packets')
    p.add_argument('--mesh',type=Path,required=True)
    p.add_argument('--start',type=float,nargs=2,required=True);p.add_argument('--end',type=float,nargs=2,required=True)
    p.add_argument('--start-height',type=float);p.add_argument('--end-height',type=float)
    args=p.parse_args()
    print(json.dumps(route(json.loads(args.mesh.read_text()),args.start,args.end,args.start_height,args.end_height)))

if __name__=='__main__':main()
