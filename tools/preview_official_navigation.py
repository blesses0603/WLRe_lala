"""Fetch one reviewed official model and preview its versioned database geometry."""
import argparse
import json
from wlre.services.world.dynamic_bundle_runtime import prepare_dynamic_runtime
from wlre.services.world.navigation_preview import PreviewRepository


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map',type=int,required=True)
    parser.add_argument('--sync',action='store_true',help='Download at most two bundles / 32 MiB for this model')
    parser.add_argument('--smooth-planar',action='store_true',help='Preview flat corridors only; reject slopes')
    parser.add_argument('--travel-mode',choices=('land','sea','sky'),default='land')
    parser.add_argument('--start',nargs=2,type=float)
    parser.add_argument('--end',nargs=2,type=float)
    args=parser.parse_args()
    if bool(args.start)!=bool(args.end):parser.error('Provide both --start and --end')
    runtime=prepare_dynamic_runtime(sync=False)
    repository=PreviewRepository(runtime.catalog_identity,runtime.stages)
    try:
        if args.start:
            result=repository.route(args.map,args.start,args.end,download=args.sync,travel_mode=args.travel_mode,smooth=args.smooth_planar)
        else:
            stage=runtime.stages.get(args.map)
            if stage is None:raise ValueError('Official stage ID unavailable; dynamic house floor model not inferred')
            mesh,origin=repository.load(stage['model_id'],download=args.sync,travel_mode=args.travel_mode)
            result=dict(model=mesh.scene_id,triangles=len(mesh.faces),origin=origin,
                        catalog_key=runtime.catalog_identity.key,can_send_packets=False)
        print(json.dumps(result,ensure_ascii=False))
    except (OSError,ValueError,RuntimeError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
