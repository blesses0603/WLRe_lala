"""Conservative status text for the server-backed hyperspace storage tab.

An unlock item in the ordinary bag is not evidence that Mark_CarryOnBank
(1291) is active. A storage delta before the initial S62 snapshot is not a
confirmed, complete cupboard inventory.
"""


def unlock_message(inventory):
    if not inventory.get('ready'):
        return '背包尚未同步；無法判斷超空間袋是否已解鎖。'
    count = sum(int(item.get('count', 0)) for item in inventory.get('items', {}).values()
                if item.get('item_id') == 34977)
    if count:
        return f'背包持有超空間袋解鎖道具 ×{count}；是否啟用仍須遊戲標記確認。'
    return '背包未持有解鎖道具；不代表尚未啟用，仍缺少解鎖標記確認。'


def storage_sync_message(storage):
    result = []
    for name, key in (('儲藏室', 'garage'), ('雜物櫃', 'materials')):
        bucket = storage.get(key, {})
        if not bucket.get('reliable', True):
            state = '同步異常，資料僅供參考，請重新登入'
        elif not bucket.get('ready'):
            state = '等待初始 S62 同步'
        else:
            amount = len(bucket.get('items', {}))
            capacity = bucket.get('capacity')
            limit = f' / {capacity}' if capacity is not None else ''
            state = f'已同步 {amount}{limit} 格（唯讀）'
        result.append(f'{name}：{state}')
    return '｜'.join(result)


def confirmed_view(bucket):
    """Hide pre-snapshot deltas, never pass ordinary bag items as storage."""
    if bucket.get('ready'):
        return bucket
    return {**bucket, 'items': {}}
