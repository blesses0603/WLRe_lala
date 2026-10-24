"""Explore official 1275 inter-scene links, read-only: never sends packets."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description='1275 官方場景拓樸唯讀預覽')
    parser.add_argument('data_catalog', type=Path)
    parser.add_argument('eve_index', type=Path)
    parser.add_argument('--from-stage', type=int)
    parser.add_argument('--to-stage', type=int)
    parser.add_argument('--scene', type=int)
    args = parser.parse_args(argv)
    if (args.from_stage is None) != (args.to_stage is None):
        parser.error('--from-stage 與 --to-stage 必須同時指定')
    from wlre.services.world.preview_1275 import load_preview
    runtime = load_preview(args.data_catalog, args.eve_index)
    result = {'revision':1275,'counts':runtime.topology['counts'],
              'can_send_packets':False, 'navmesh_verified':False}
    if args.scene is not None:
        if args.scene not in runtime.stages:
            parser.error('1275 官方資料沒有此場景')
        result['scene'] = runtime.stages[args.scene]
        result['markers'] = runtime.topology['markers'].get(args.scene, [])
        result['eve_links'] = runtime.topology['eve_links'].get(args.scene, [])
        result['binary_links'] = runtime.topology['binary_links'].get(args.scene, [])
        result['verified_eve_doors'] = runtime.doors.get(args.scene, [])
    if args.from_stage is not None:
        result['route'] = runtime.plan_stages(args.from_stage, args.to_stage)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('1275 場景拓樸僅供分析；A*導航網格及傳送封包尚未驗證，'
          '不會移動角色或觸發門事件。')


if __name__ == '__main__':
    main()
