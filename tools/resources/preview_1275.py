"""Launch LaLa's strictly read-only 1275 NPC/shop/item/recipe/map preview.

Usage:
  python -m tools.resources.preview_1275 DATA.zip EVE.zip --scene 10000
  python -m tools.resources.preview_1275 DATA.zip EVE.zip --shop 10000:7
  python -m tools.resources.preview_1275 DATA.zip EVE.zip --item 39852 --recipe 39852
No credentials, game installation, packets or server access required.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from wlre.services.world.preview_1275 import load_preview


def _shop_key(value):
    try:
        scene, index = (int(x) for x in value.split(':'))
        if not 0 <= scene <= 65535 or not 0 <= index <= 65535:
            raise ValueError()
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError('商店索引請使用 地圖ID:事件索引')
    return scene, index


def main(argv=None):
    parser = argparse.ArgumentParser(description='LaLa 1275 官方資料唯讀預覽（不送遊戲封包）')
    parser.add_argument('data', type=Path, help='WLRE_LaLa_1275_全資源差異與校驗包.zip')
    parser.add_argument('eve', type=Path, help='WLRE_1275_Eve_NPC_索引包.zip')
    parser.add_argument('--scene', type=int, help='預覽此場景的 NPC，最多輸出前 40 筆')
    parser.add_argument('--shop', type=_shop_key, help='預覽商店，格式 地圖ID:事件索引')
    parser.add_argument('--item', type=int, help='查看 1275 物品基本資料')
    parser.add_argument('--recipe', type=int, help='查看 1275 製作配方')
    parser.add_argument('--portal', type=int, help='查看 1275 場景與傳送安全狀態')
    parser.add_argument('--door-index', type=int, help='搭配 --portal 查看 1275 官方門事件索引')
    args = parser.parse_args(argv)
    if args.door_index is not None and args.portal is None:
        parser.error('--door-index 必須搭配 --portal')
    source = load_preview(args.data, args.eve)
    result = {'revision': source.revision, 'mode': 'read_only',
              'packet_sending_enabled': source.can_send_packets,
              'counts': {'npcs': sum(len(v) for v in source.npc_index.scenes.values()),
                         'items': len(source.items),
                         'recipes': len(source.recipes),
                         'scenes': len(source.scene_ids)}}
    if args.scene is not None:
        results = source.npc_for_scene(args.scene)
        result['npcs'] = {'scene': args.scene, 'count': len(results),
                          'first_40': results[:40]}
    if args.shop is not None:
        row = source.shop_for_scene(*args.shop)
        result['shop'] = row if row is not None else {'reason': '沒有已核對的 1275 商店'}
    if args.item is not None:
        result['item'] = {'id': args.item, 'data': source.items.get(args.item)}
    if args.recipe is not None:
        result['recipe'] = source.recipe(args.recipe)
    if args.portal is not None:
        result['portal'] = source.portal_status(args.portal, args.door_index)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('唯讀預覽：1275 網路登入、NPC 交易、傳點觸發、製作排程均未開放。')


if __name__ == '__main__':
    main()
