"""Official 1262 NPC weapon/item shop offers, deliberately read-only.

Eve.NewInteract formKind=2/3 holds item IDs, not NPC TalkData text IDs.
Shop.SetDataFromEvent uses each kind=3 row's id as offer index and
dataBaseId as item ID. Verified price, sellPrice and restrict values now come from ItemData_C;
transaction totals, live gold and actual trades are STILL unverified.

No purchase, sell, or real-money packet is sent from this module.
"""
from wlre.network.wire import ProtocolError, Packet, Writer
from wlre.services.items.catalog import item_name
from wlre.services.world.npc_item_data import item_catalog, sellable
from wlre.services.world.npc_interact import NPCInteractIndex

SHOP_TYPES = {2: '武器商店', 3: '道具商店'}


def shop_catalog(scene, interact_index, *, index=None):
    """Return a verified shop's product IDs, never claim a price without data.

    The caller must additionally check the live manually-opened S20 event,
    scene and index. Offline data alone never authorizes a transaction.
    """
    if type(scene) is not int or type(interact_index) is not int:
        return None
    lookup = index if index is not None else NPCInteractIndex()
    data = lookup.get(scene, interact_index)
    if not data or data.get('form_kind') not in SHOP_TYPES:
        return None
    # Lossy/corrupt catalogues never permit a transaction or fabricated price.
    try:
        item_rows = item_catalog()
    except (OSError, EOFError, ValueError, UnicodeError):
        item_rows = {}
    products = []
    seen = set()
    for entry in data['items']:
        if entry['kind'] == 4:
            # Official exit button. A shop close uses C20-9 with empty body.
            continue
        if entry['kind'] != 3 or entry['database_kind'] != 2:
            return None
        item_id, product_index = entry['text_id'], entry['id']
        if (type(item_id) is not int or not 1 <= item_id <= 65535
                or type(product_index) is not int or not 1 <= product_index <= 255
                or product_index in seen):
            return None
        seen.add(product_index)
        item = item_rows.get(item_id)
        products.append({
            'offer_index': product_index,
            'item_id': item_id,
            'name': item['name'] if item else item_name(item_id),
            'price_gold': item['price'] if item else None,
            'sell_price_gold': item['sell_price'] if item else None,
            'npc_sell_allowed': sellable(item),
            'buy_enabled': False,
        })
    if not products:
        return None
    complete = bool(item_rows) and all(p['price_gold'] is not None for p in products)
    return {'scene': scene, 'interact_index': interact_index,
            'form_kind': data['form_kind'], 'title': SHOP_TYPES[data['form_kind']],
            'products': products, 'verified_prices': False,
            'item_data_verified': complete,
            'reason': ('官方 ItemData_C 基礎價已核對；仍須核實折扣、伺服器金幣與交易結果，禁止實際交易。'
                       if complete else '官方 ItemData_C 校驗失敗，價格不可用，禁止實際交易。')}


def purchase_wire_layout(index, count):
    """Reference-only C27-1 layout. Not wired into command dispatch.

    Always validate scalar types and bounds; no live purchase can be triggered
    by calling the user-facing NPC command router in this phase.
    """
    if (type(index) is not int or not 1 <= index <= 255
            or type(count) is not int or not 1 <= count <= 0xffffffff):
        raise ProtocolError('購買商品索引或數量超出官方 C27-1 欄位')
    return Packet(27, 1, Writer().u8(index).u32(count).build())


def sell_wire_layout(bag_index, count):
    """Reference-only C27-3 layout; no live sell command is registered."""
    if (type(bag_index) is not int or not 0 <= bag_index <= 255
            or type(count) is not int or not 1 <= count <= 255):
        raise ProtocolError('販售背包格位或數量超出官方 C27-3 欄位')
    return Packet(27, 3, Writer().u8(bag_index).u8(count).build())


def draft_purchase(catalog, offer_index, count):
    """A fail-closed preview: never return a packet or invented currency cost."""
    if not isinstance(catalog, dict) or catalog.get('verified_prices') is not False:
        raise ProtocolError('商品來源不合法，無法建立交易預覽')
    if type(count) is not int or not 1 <= count <= 9999:
        raise ProtocolError('預覽數量必須是 1～9999 的整數')
    rows = [item for item in catalog.get('products', ())
            if item['offer_index'] == offer_index and type(offer_index) is int]
    if len(rows) != 1:
        raise ProtocolError('找不到官方商品索引')
    price = rows[0]['price_gold']
    base_total = None if type(price) is not int else price * count
    if base_total is not None and base_total > 0xffffffff:
        raise ProtocolError('基礎交易金額超過官方 32-bit 金幣範圍')
    return {'item_id': rows[0]['item_id'], 'count': count,
            'base_unit_gold': price, 'base_total_gold': base_total,
            'total_gold': None, 'enabled': False,
            'reason': catalog['reason']}
