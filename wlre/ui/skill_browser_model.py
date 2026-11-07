"""Read-only presentation of server-confirmed skills; never grants skills."""
import re

CATEGORIES = ('全部', '物理', '魔法', '輔助', '被動', '其他')
WEAPONS = ('刀／劍／矛／拳刃／斧頭', '空手／拳套／棒槌', '魔杖／其他魔法武器', '弓弩', '槍')


def actor_key(actor):
    return f"actor{actor['pid']}_{actor.get('npc_index', 0)}"


def skill_key(actor, skill_id):
    return f"skill{actor['pid']}_{actor.get('npc_index', 0)}_{skill_id}"


def plain_text(value):
    # Official descriptions may carry Unity rich-text tags. Never render them as UI.
    return re.sub(r'</?(?:color|size|b|i)(?:=[^>]*)?>', '', str(value or ''), flags=re.I).replace('\\n', '\n')


def level_text(row, data):
    level, limit = row['level'], data.get('LvLimit')
    if type(limit) is int and limit > 0:
        return f'Lv.{level} / {limit}' + ('  MAX' if level >= limit else '')
    return f'Lv.{level}（上限待同步）'


def detail_text(row, data, live, battle):
    description = plain_text(data.get('description')) or '此版本尚未同步技能說明。'
    weapon_fields = [data.get(f'WeaponKind{i}') for i in range(1, 6)]
    weapons = '、'.join(label for label, enabled in zip(WEAPONS, weapon_fields) if enabled == 1)
    if any(value is None for value in weapon_fields): weapons = '待同步'
    elif not weapons: weapons = '無可用武器'
    conditions = '；'.join(row.get('reasons', ())) or '基礎條件可用（送出時仍會重新核對）'
    if not live: conditions = '未連線，僅顯示最後同步資料。\n' + conditions
    elif not battle: conditions = '目前不在戰鬥回合，僅供檢視。\n' + conditions
    return (f"{description}\n\n適用武器\n{weapons}\n\n使用條件\n{conditions}\n\n"
            f"資料來源：{row.get('source') or '待同步'}\n技能 ID：{row['id']}")


def matches(row, actor, query, category):
    return ((category == '全部' or row['category'] == category)
            and (not query or query.casefold() in
                 (actor.get('name', '') + row['name'] + str(row['id'])).casefold()))
