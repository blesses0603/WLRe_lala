"""Bounded, read-only S23/S26/S27 transaction evidence for manual review.

Official protocol 1262 has no verified client order nonce. This module does not
send C27 purchases/sales and MUST NOT authorize or declare a payment settled.
An offline probe can only classify whether independent packet observations
appear internally consistent, or are absent/ambiguous.
"""
from wlre.network.wire import ProtocolError

RELEVANT = frozenset((
    'bag_snapshot','bag_add','bag_delete','bag_sell',
    'gold_snapshot','gold_delta','gold_limit',
    'shop_purchase_result','sale_notice',
))
MAX_EVENTS = 96
MAX_UINT32 = 0xffffffff


def defaults():
    return {'events': [], 'revision': 0,
            'status': '無交易觀測資料（未啟用付款）'}


def observe(state, event):
    """Capture only scalar transaction facts AFTER normal state.apply handlers."""
    kind = event.get('type')
    if kind == 'role_list_available' or kind == 'login_result':
        state.shop_evidence = defaults()
        return
    if kind not in RELEVANT:
        return
    entry = {'packet': state.packet_count, 'type': kind,
             'inventory_revision': state.inventory.get('revision',0),
             'inventory_reliable': bool(state.inventory.get('ready')
                                        and state.inventory.get('reliable')),
             'gold_revision': state.gold.get('revision',0),
             'gold_reliable': bool(state.gold.get('ready')
                                  and state.gold.get('reliable'))}
    if kind == 'bag_add':
        item = event.get('item') or {}
        entry.update(item_id=item.get('item_id'), count=item.get('count'),
                     index=item.get('index'))
    elif kind in ('bag_delete','bag_sell'):
        entry.update(index=event.get('index'),count=event.get('count'))
        # S27-6 contains a gold u32, but official Bag.ReceiveSellItemResult
        # reads and discards it; it is NOT an authoritative balance.
        if kind == 'bag_sell':
            entry['s27_gold_field'] = event.get('gold')
    elif kind == 'bag_snapshot':
        entry['capacity'] = event.get('capacity')
    elif kind == 'gold_snapshot':
        entry['amount'] = event.get('amount')
    elif kind == 'gold_delta':
        entry['delta'] = event.get('delta')
    elif kind in ('shop_purchase_result','sale_notice'):
        entry['result'] = event.get('result')
    events = (state.shop_evidence.get('events',[]) + [entry])[-MAX_EVENTS:]
    state.shop_evidence = {'events':events,
        'revision':state.shop_evidence.get('revision',0)+1,
        'status':'已記錄 S23／S26／S27 封包；並非交易已完成'}


def classify(evidence, *, kind, start_packet, item_id, count, expected_gold_delta,
             bag_slot=None):
    """Offline correlation only, NEVER authorization or confirmation of settlement.

    Caller supplies a trusted order description recorded at the instant its
    *single* command was sent, not a retrospective guess. No live command
    currently creates such a descriptor. Other inventory/gold traffic,
    duplicates, untrusted state or stale history make result uncertain.
    """
    if (kind not in ('buy','sell') or type(start_packet) is not int
            or start_packet < 0 or type(item_id) is not int
            or not 1 <= item_id <= 65535
            or type(count) is not int or not 1 <= count <= 255
            or type(expected_gold_delta) is not int
            or not -MAX_UINT32 <= expected_gold_delta <= MAX_UINT32
            or (kind == 'buy' and expected_gold_delta >= 0)
            or (kind == 'sell' and expected_gold_delta <= 0)
            or (kind == 'sell' and (type(bag_slot) is not int
                 or not 0 <= bag_slot <= 255))):
        raise ProtocolError('離線交易對帳的項目、數量或金額非法')
    entries=evidence.get('events',[])
    if not isinstance(entries,list) or len(entries)>MAX_EVENTS:
        raise ProtocolError('離線交易事件來源不合法')
    if entries and type(entries[0].get('packet')) is int and (
            entries[0]['packet']>start_packet+1):
        return {'status':'uncertain','reason':'事件已超出保留窗口，無法對帳'}
    records=[e for e in entries if type(e.get('packet')) is int
             and e['packet']>start_packet]
    if not records:
        return {'status':'pending','reason':'未觀測到付款、背包或結果回覆'}
    result_kind='shop_purchase_result' if kind=='buy' else 'sale_notice'
    if any(e.get('type') in ('shop_purchase_result','sale_notice')
           and e.get('type') != result_kind for e in records):
        return {'status':'uncertain','reason':'觀測窗口包含其他種類交易結果，無法唯一歸屬'}
    results=[e for e in records if e['type']==result_kind]
    if len(results)>1:
        return {'status':'uncertain','reason':'交易結果可能重複或包含其他交易'}
    if results and results[0].get('result')!=(0 if kind=='buy' else 1):
        conflicting=any(e['type'] in ('gold_delta','bag_add','bag_delete','bag_sell')
                        for e in records)
        return {'status':'uncertain' if conflicting else 'rejected',
                'reason':('伺服器宣告失敗但另有背包／金幣異動，無法安全判定'
                          if conflicting else '伺服器拒絕交易，未觀察到這筆交易的相關異動')}
    currencies=[e for e in records if e['type']=='gold_delta']
    items=[e for e in records if e['type'] in ('bag_add','bag_delete','bag_sell')]
    if (any(e['type'] in ('gold_snapshot','gold_limit','bag_snapshot') for e in records)
            or len(currencies)>1 or
            any(not e.get('gold_reliable') or not e.get('inventory_reliable')
                for e in currencies+items)):
        return {'status':'uncertain','reason':'資料重新初始化、其他金幣異動或同步失效'}
    if currencies and currencies[0].get('delta')!=expected_gold_delta:
        return {'status':'uncertain','reason':'S26 金幣變更與預期金額不同，可能有折扣或其他交易'}
    if kind=='buy':
        if any(e['type']!='bag_add' or e.get('item_id')!=item_id
               or type(e.get('count')) is not int or e['count']<=0 for e in items):
            return {'status':'uncertain','reason':'S23 背包異動不屬於這筆商品'}
        total=sum(e['count'] for e in items)
        if total>count:
            return {'status':'uncertain','reason':'S23 入袋數量超過本筆預期'}
        items_done=(total==count)
    else:
        if len(items)>1 or any(e['type']!='bag_sell'
               or e.get('index')!=bag_slot or e.get('count')!=count for e in items):
            return {'status':'uncertain','reason':'S27-6 販售格位或數量與預期不同'}
        items_done=len(items)==1
    if results and currencies and items_done:
        # No server transaction ID: indistinguishable overlapping operations.
        # Never label a matching observation "settled" or enable more trades.
        return {'status':'observed_consistent',
                'reason':'S23/S26/S27 觀測一致；因缺少伺服器交易識別碼，仍待實機人工對帳'}
    return {'status':'pending','reason':'等待缺少的 S23、S26 或 S27 證據；禁止重送'}
