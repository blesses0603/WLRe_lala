"""Review a fingerprinted official navigation cache without enabling movement."""
import json
from pathlib import Path
from wlre.services.world.astar_cache import review_cache, MAX_BYTES

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();target=args.output.resolve()
    if any((p/'.git').exists() for p in (target,*target.parents)):
        parser.error('Decoded official data must remain outside Git worktrees')
    if args.input.stat().st_size>MAX_BYTES:parser.error('Input exceeds review quota')
    result=review_cache(args.input.read_bytes())
    with target.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=True)
    print(json.dumps({'tiles':len(result['mesh']['tiles']),'origin_max_error':result['origin_max_error'],
                      'live_movement_verified':False,'can_send_packets':False}))


if __name__=='__main__':main()
