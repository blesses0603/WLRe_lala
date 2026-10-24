import argparse
import getpass
import json
import sys
from pathlib import Path
from wlre.services.world.map_names import map_label
from wlre import __version__


def dump(value, file=sys.stdout):
    print(json.dumps(value, ensure_ascii=False), file=file, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=f"WLRE 1262 headless research client v{__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("nav-list", help="list bundled scene resources and navigation availability")
    p = sub.add_parser('map-coordinate',help='convert logical-map packet XY to cached navigation XZ')
    p.add_argument('map_id',type=int)
    p.add_argument('x',type=float)
    p.add_argument('y',type=float)
    p.add_argument('--inverse',action='store_true',help='convert navigation XZ back to packet XY')
    p = sub.add_parser('map-route',help='offline route using logical-map ID and packet XY')
    p.add_argument('map_id',type=int)
    p.add_argument('--start',type=float,nargs=2,required=True)
    p.add_argument('--end',type=float,nargs=2,required=True)
    p.add_argument('--start-height',type=float)
    p.add_argument('--end-height',type=float)
    p = sub.add_parser("nav-query", help="query an offline navigation surface using serialized Int3 X/Z")
    p.add_argument("scene")
    p.add_argument("x", type=float)
    p.add_argument("z", type=float)
    p.add_argument("--height", type=float)
    p = sub.add_parser("nav-route", help="preview an offline geometric route; never sends movement")
    p.add_argument("scene")
    p.add_argument("--start", type=float, nargs=2, required=True, metavar=("X","Z"))
    p.add_argument("--end", type=float, nargs=2, required=True, metavar=("X","Z"))
    p.add_argument("--start-height", type=float)
    p.add_argument("--end-height", type=float)
    p = sub.add_parser("live", help="experimental TCP client; not official-server validated")
    p.add_argument("host")
    p.add_argument("--port", type=int, default=16988)
    p.add_argument("--profile", required=True)
    p.add_argument("--account")
    p.add_argument("--login-kind", type=int, choices=[0, 2, 3, 4], default=2)
    p.add_argument("--platform", type=int)
    p.add_argument("--language", type=int)
    p.add_argument("--role-index", type=int, choices=[1, 2])
    p.add_argument("--verify-first", action="store_true")
    p.add_argument("--duration", type=float, default=15)
    args = parser.parse_args(argv)
    try:
        if args.command in ('map-coordinate','map-route'):
            from wlre.services.world.coordinates import Coordinates
            from wlre.services.world.navigation import Repository
            converter = Coordinates()
            if args.command=='map-coordinate':
                function = converter.to_packet if args.inverse else converter.to_navigation
                stage,scene,_ = converter.mapping(args.map_id)
                dump({'logical_map':args.map_id,'map_label':map_label(args.map_id),'scene_resource':scene,
                      'point':function(args.map_id,args.x,args.y),
                      'coordinate_space':'packet_xy' if args.inverse else 'navcache_vertices_b_int3_xz',
                      'formula_source_checked':True,'live_movement_verified':False})
            else:
                dump(converter.route(Repository(),args.map_id,args.start,args.end,args.start_height,args.end_height))
        elif args.command.startswith('nav-'):
            from wlre.services.world.navigation import Repository
            repository = Repository()
            if args.command == 'nav-list':
                dump({'type':'navigation_catalog','scenes':repository.catalog,
                      'source_revision':repository.source_revision,'status':repository.status})
            else:
                mesh = repository.load(args.scene)
                if args.command == 'nav-query':
                    face,point = mesh.locate(args.x,args.z,args.height)
                    dump({'type':'navigation_surface','scene_resource':mesh.scene_id,
                          'source':mesh.source,'can_send_packets':False,
                          'face':face,'point':point,'coordinate_space':'navcache_vertices_b_int3',
                          'network_coordinates_verified':False})
                else:
                    dump(mesh.route(args.start,args.end,args.start_height,args.end_height))
        else:
            from wlre.network.client import run_client
            profile = json.loads(Path(args.profile).read_text(encoding="utf-8-sig"))
            password = getpass.getpass("Password (not saved): ") if args.account else None
            result = run_client(args.host, args.port, profile, dump, account=args.account,
                                password=password, login_kind=args.login_kind, platform=args.platform,
                                language=args.language, role_index=args.role_index, duration=args.duration,
                                verify_first=args.verify_first)
            dump({"type": "summary", "state": result.snapshot()})
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Errors never include raw packets or credential values.
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
