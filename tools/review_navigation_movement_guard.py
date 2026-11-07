"""Offline movement refusal regression using verified cached geometry; never a live session."""
import argparse
import json
from pathlib import Path
from unittest.mock import Mock
from wlre.services.world.navigation_database import load_cache,database_path
from wlre.services.world.navigation import Mesh
from wlre.services.world.movement import Movement
from wlre.network.wire import ProtocolError
from wlre.core.state import State

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.report.read_text());stages=json.loads((args.snapshot/'current-stages.json').read_text());results=[]
    for row in report['comparisons']:
     control=row.get('same_geometry_control',{})
     if control.get('unfiltered_algorithm',{}).get('allowed_by_preview_graph') is not False:continue
     scene=row['map_id'];stage=stages[str(scene)];decoded=load_cache(database_path(),report['catalog_key'],stage['model_id']);mesh=Mesh(decoded['mesh']);origin=decoded['origin'];offset=6992 if stage['map_height']==65535 else stage['map_height']
     start=row['input_xy']['start'];end=row['input_xy']['end']
     def graph(p):return p[0]*10-origin[0],(offset-p[1])*10-origin[2]
     route=mesh.route(graph(start),graph(end));state=State();state.player=dict(role_id=1,scene=scene);state.confirm_location(scene,*start,'synthetic_test_fix')
     converter=Mock();converter.route.return_value=route;movement=Movement(converter,Mock())
     try:movement.start(state,*end,0)
     except ProtocolError as error:assert '僅供預覽' in str(error)
     else:raise AssertionError('Unverified real geometry was accepted')
     assert movement.tick(state,1)==[] and not movement.active
     converter.to_packet.assert_not_called()
     results.append(dict(map_id=scene,mode=row['travel_mode'],blocked=True,can_send_packets=False))
    assert len(results)==12
    print(json.dumps(results));args.output.write_text(json.dumps(results,indent=2))


if __name__ == "__main__":
    main()
