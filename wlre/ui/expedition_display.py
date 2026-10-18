"""Readable expedition time and rewards, without inventing localized names."""
from wlre.services.items.combat_resources import item_name


CURRENCIES = {1: '漂流幣', 2: '綠鑽', 3: '綁定綠鑽', 4: '紫鑽', 5: '組織硬幣',
              6: '組織發展值', 7: '建設材料箱', 8: '星力', 9: '罐頭幣', 10: '紅利',
              11: '組織寶箱碎片', 12: '許願星星', 13: '遠征幣', 14: '群星幣'}


def task_name(quest):
    return quest.get('name') or '任務名稱待補齊'


def time_text(seconds):
    hours, minutes = divmod(int(seconds) // 60, 60)
    return f'{hours} 小時 {minutes} 分鐘' if minutes and hours else f'{hours} 小時' if hours else f'{minutes} 分鐘'


def reward_text(award):
    kind, sid, count = award.get('kind', 0), award.get('id', 0), award.get('value', 0)
    if not kind or count <= 0: return ''
    if kind in (10, 11): name = item_name(sid)
    elif kind == 6: name = CURRENCIES.get(sid, f'貨幣 {sid}')
    elif kind == 1: name = '經驗'
    elif kind == 2: name = '漂流幣'
    else: name = '其他獎勵'
    return f'{name} × {count:,}'


def rewards_text(quest):
    rows = []
    if quest.get('expedition_exp'): rows.append(f"遠征經驗 × {quest['expedition_exp']:,}")
    if quest.get('exp'): rows.append(f"經驗 × {quest['exp']:,}")
    rows.extend(filter(None, (reward_text(a) for a in quest.get('rewards', []))))
    special = reward_text(quest.get('special_reward', {}))
    if special and quest.get('special_rate', 0) > 0:
        rows.append('機率獎勵：' + special)
    return '／'.join(rows) or '無獎勵資料'
