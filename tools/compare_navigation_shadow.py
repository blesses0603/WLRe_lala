"""Compare legacy and cached official paths; CDN metadata checks, no movement or bundle downloads."""
import argparse
import json
from wlre.services.world.dynamic_bundle_runtime import prepare_dynamic_runtime
from wlre.services.world.navigation_shadow import compare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', type=int, required=True)
    parser.add_argument('--start', nargs=2, type=float, required=True)
    parser.add_argument('--end', nargs=2, type=float, required=True)
    parser.add_argument('--travel-mode', choices=('land', 'sea', 'sky'), default='land')
    args = parser.parse_args()
    try:
        runtime = prepare_dynamic_runtime(sync=False)
        result = compare(args.map, args.start, args.end, travel_mode=args.travel_mode,
                         runtime_getter=lambda: runtime)
        result['context'] = 'Standalone snapshot; no live player state or subsequent CDN version observation.'
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
