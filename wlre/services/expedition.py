"""Server-confirmed expedition automation. Never retry unconfirmed consumption."""
from wlre.core.state_ownership import writes
from wlre.services.items import reservations
from wlre.services.coordination import reason as coordination_reason
import copy
import math
import time

from wlre.network.wire import Packet, Writer, ProtocolError
from wlre.services.expedition_data import load_catalog
from wlre.services.items.combat_resources import CAT, available
from wlre.core.inventory_updates import STACKABLE
from wlre.services.expedition_teams import choose_members, condition_met, success_details


def defaults():
    return {'ready': False, 'outpost_ready': False, 'roles': {}, 'teams': {}, 'quests': {},
            'level': None, 'revision': 0, 'enabled': False, 'pending': None,
            'uncertain': False, 'status': '尚未啟動', 'settings': {}, 'claimed': 0}


def apply_expedition(state, event):
    e = state.expedition
    kind = event['type']
    if kind == 'outpost_snapshot':
        e.update(outpost_ready=True, roles={str(r['index']): r for r in event['roles']})
    elif kind == 'outpost_role':
        e['roles'][str(event['role']['index'])] = event['role']
    elif kind == 'outpost_remove':
        e['roles'].pop(str(event['index']), None)
    elif kind in ('outpost_status', 'outpost_faith', 'outpost_attribute'):
        role = e['roles'].get(str(event['index']))
        if role:
            if kind == 'outpost_status': role['state'] = event['state']
            elif kind == 'outpost_faith': role['faith'] = event['faith']
            elif event['kind'] == 64: role['faith'] = event['value']
            elif event['kind'] in (27, 28, 29, 30, 33, 35):
                key = {27: 'int', 28: 'str', 29: 'con', 30: 'agi', 33: 'wis', 35: 'level'}[event['kind']]
                role['stats'][key] = event['value']
    elif kind == 'expedition_snapshot':
        e.update(ready=True, teams={str(i + 1): with_deadline({**t, 'index': i + 1}) for i, t in enumerate(event['teams'])},
                 quests={str(i + 1): q for i, q in enumerate(event['quests'])}, level=event['level'])
    elif kind == 'expedition_team':
        t = event['team']; e['teams'][str(t['index'])] = with_deadline(t)
    elif kind == 'expedition_time':
        t = e['teams'].get(str(event['index']))
        if t: t.update(minutes=event['minutes'], due=time.monotonic() + event['minutes'] * 60)
    elif kind == 'expedition_quests': e['quests'] = event['quests']
    elif kind == 'expedition_level': e['level'] = event['level']
    elif kind == 'expedition_result':
        e['teams'][str(event['index'])] = {'index': event['index'], 'quest': 0, 'members': [0]*4, 'minutes': 0}
    elif kind == 'expedition_rejected':
        e.update(enabled=False, status=f"伺服器拒絕遠征操作（S31-{event['source']} 代碼 {event['code']}）")
        # A rejection does not prove consumption did not happen.
        if e['pending']: e['uncertain'] = True
    else:
        return
    e['revision'] += 1


def with_deadline(team):
    return {**team, 'due': time.monotonic() + team['minutes'] * 60}


def preferences():
    return {'faith_min': 80, 'item_id': 0, 'min_hours': 0, 'min_success': 75, 'quests': [], 'auto_claim': True}


def validate(value):
    if not isinstance(value, dict): raise ProtocolError('遠征設定格式錯誤')
    result = preferences()
    for key, low, high in (('faith_min', 1, 100), ('item_id', 0, 65535)):
        v = value.get(key, result[key])
        if type(v) is not int or not low <= v <= high: raise ProtocolError('好友度門檻或物品編號錯誤')
        result[key] = v
    hours = value.get('min_hours', 0)
    if type(hours) not in (int, float) or not math.isfinite(hours) or not 0 <= hours <= 24:
        raise ProtocolError('任務時間門檻必須介於 0 至 24 小時')
    result['min_hours'] = hours
    minimum = value.get('min_success', 75)
    if type(minimum) not in (int, float) or not math.isfinite(minimum) or not 0 <= minimum <= 100:
        raise ProtocolError('最低成功率必須介於 0 至 100%')
    result['min_success'] = minimum
    auto_claim = value.get('auto_claim', True)
    if type(auto_claim) is not bool: raise ProtocolError('自動領獎設定必須為布林值')
    result['auto_claim'] = auto_claim
    for key, maximum in (('quests', 50),):
        values = value.get(key, [])
        if (not isinstance(values, list) or len(values) > maximum
                or any(type(v) is not int or not 1 <= v <= 65535 for v in values)
                or len(set(values)) != len(values)):
            raise ProtocolError('遠征任務清單格式錯誤')
        result[key] = list(values)
    return result


def faith_gain(item_id):
    item = CAT['items'].get(str(item_id), {})
    if item.get('special') != 0: return 0
    values = [a['value'] - 100 for a in item.get('attributes', []) if a['kind'] == 64]
    return values[-1] if values and values[-1] > 0 else 0


def recovery_stock(inventory):
    """Only server-backed, unlocked, unreserved, non-expiring faith items."""
    if not inventory.get('ready') or not inventory.get('reliable'): return {}
    stock = {}
    for index, item in inventory.get('items', {}).items():
        sid = item['item_id']
        if (not faith_gain(sid) or item.get('locked') or item.get('limited_time', 0)
                or item.get('available_time', 0)): continue
        amount = available(inventory, index)
        if amount: stock[sid] = stock.get(sid, 0) + amount
    return stock


def duration(quest, level):
    # Text.GetTimeStr consumes minutes. Lua rounds reduced minutes first.
    return math.floor(quest['minutes'] * (1000 - level['reduction']) / 1000 + .5) * 60


def condition_ok(quest, roles, npcs=None):
    return condition_met(quest['condition'], roles, npcs) is True


def blocked(state):
    return coordination_reason(state,'expedition')


def item_totals(inventory):
    totals = {}
    for item in inventory.get('items', {}).values():
        sid = item['item_id']
        totals[sid] = totals.get(sid, 0) + item['count']
    return totals


def claim_space(quest):
    """Reserve empty slots for every possible item reward; don't assume stacks."""
    if 'rewards' not in quest or 'special_reward' not in quest: return None
    need = 0
    for reward in quest['rewards'] + [quest['special_reward']]:
        kind, sid, count = reward['kind'], reward['id'], reward['value']
        if kind in (10, 11):
            if str(sid) not in STACKABLE or count < 0: return None
            need += math.ceil(count / 200) if kind == 10 and STACKABLE[str(sid)] else count
        elif kind not in (0, 1, 2, 6, 12, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31):
            return None  # e.g. an automatically opened lucky bag needs its own data
    return need


class Expedition:
    def __init__(self, catalog=None):
        self.catalog_override = catalog
        self.catalog = catalog
        self.pending = None
        self.next_check = 0

    @writes('expedition')
    def start(self, state, settings):
        e = state.expedition
        if e['uncertain'] or self.pending: raise ProtocolError('前次遠征操作未確認，請重新登入同步')
        settings = validate(settings)
        self.catalog = self.catalog_override if self.catalog_override is not None else load_catalog()
        if not self.catalog.get('tasks') or not self.catalog.get('levels'):
            raise ProtocolError('內建遠征資料不完整，請更新完整程式')
        if not e['ready'] or not e['outpost_ready']: raise ProtocolError('等待遠征與駐紮所資料同步')
        level = self.catalog['levels'].get(str(e['level']))
        if not level: raise ProtocolError('此遠征等級缺少官方資料')
        reason = blocked(state)
        if reason: raise ProtocolError(reason)
        e.update(enabled=True, settings=settings, status=f"自動派遣已啟動（預計超過 {settings['min_hours']:g} 小時）")
        self.next_check = 0

    @writes('expedition')
    def stop(self, state, reason='已停止自動派遣'):
        state.expedition.update(enabled=False, status=reason + ('；仍在等待已送出的操作回覆' if self.pending else ''))

    @writes('expedition')
    def observe(self, event, state):
        p = self.pending
        if not p: return
        if event['type'] == 'expedition_rejected':
            self.stop(state, state.expedition['status'])
            return
        if p['kind'] == 'claim':
            if event['type'] == 'expedition_result' and event['index'] == p['index']:
                p['result'] = event
                p['expected'] = {}
                for award in event.get('rewards', []):
                    if award['kind'] in (10, 11):
                        sid = award['id']
                        p['expected'][sid] = p['expected'].get(sid, 0) + award['value']
                    elif award['kind'] not in (0, 1, 2, 6, 12, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31):
                        state.expedition['uncertain'] = True
                        self.stop(state, '領獎結果含未支援的獎勵類型，請重新登入同步')
                        return
            if p.get('result') and state.inventory.get('ready') and state.inventory.get('reliable'):
                totals = item_totals(state.inventory)
                if all(totals.get(sid, 0) >= p['before'].get(sid, 0) + count for sid, count in p['expected'].items()):
                    state.expedition['claimed'] += 1
                    self.confirm(state, f"隊伍 {p['index']} 領獎與物品入包已確認，繼續自動派遣")
            return
        if p['kind'] == 'dispatch' and event['type'] in ('expedition_team', 'expedition_snapshot'):
            teams = [event['team']] if event['type'] == 'expedition_team' else event['teams']
            if any(t['quest'] == p['quest'] and sorted(v for v in t['members'] if v) == sorted(p['members']) for t in teams):
                self.confirm(state, '派遣已由伺服器確認')
        elif p['kind'] == 'faith':
            role = state.expedition['roles'].get(str(p['index']))
            if not role or role['npc_id'] != p['npc_id']:
                state.expedition['uncertain'] = True
                self.stop(state, '補好友度對象已變更，請重新登入同步')
                return
            if event['type'] in ('outpost_faith', 'outpost_attribute', 'outpost_role', 'outpost_snapshot'):
                p['faith_ok'] = role['faith'] >= p['target']
            if event['type'] == 'bag_delete':
                index = str(event['index'])
                if index in p['consumed']: p['consumed'][index] += event['count']
            if event['type'] == 'bag_snapshot':
                inv = state.inventory
                for index, (before, used) in p['slots'].items():
                    current = inv['items'].get(index)
                    if current is None: p['consumed'][index] = before['count']
                    elif current['item_id'] == before['item_id'] and current.get('serial') == before.get('serial'):
                        p['consumed'][index] = before['count'] - current['count']
            if p['faith_ok'] and all(p['consumed'][index] == used for index, (_, used) in p['slots'].items()):
                self.confirm(state, '好友度與物品扣除已確認')

    @writes('expedition')
    def confirm(self, state, text):
        if self.pending and self.pending['kind'] == 'faith':
            reservations.release(state.inventory,'expedition')
        self.pending = None
        state.expedition.update(pending=None, status=text)
        self.next_check = time.monotonic() + 1

    @writes('expedition')
    def tick(self, state, now=None):
        now = time.monotonic() if now is None else now
        e = state.expedition
        if self.pending:
            if now >= self.pending['due'] and not e['uncertain']:
                e['uncertain'] = True
                reservations.uncertain(state.inventory,'expedition')
                self.stop(state, '遠征操作逾時未確認，已停止且不會重送；請重新登入同步')
            return []
        if not e['enabled'] or e['uncertain'] or now < self.next_check: return []
        self.next_check = now + 2
        reason = blocked(state)
        if reason:
            e['status'] = reason
            return []
        cfg = e['settings']
        if cfg['auto_claim']:
            completed = sorted((t for t in e['teams'].values() if t['quest'] and now > t.get('due', math.inf)), key=lambda t: t['index'])
            if completed:
                return self.claim(state, completed[0], now)
        busy = {v for t in e['teams'].values() if t['quest'] for v in t['members'] if v}
        roles = [r for r in e['roles'].values() if r['state'] == 0 and r['npc_id'] not in busy]
        if not roles:
            e['status'] = '沒有閒置夥伴；等待完成遠征並領取結果'
            return []
        lv = self.catalog['levels'].get(str(e['level']))
        if not lv:
            self.stop(state, '遠征等級資料缺失')
            return []
        if not any(not t['quest'] and 1 <= t['index'] <= lv['teams'] for t in e['teams'].values()):
            e['status'] = '沒有已解鎖的空閒隊伍'
            return []
        occupied_areas = {self.catalog['tasks'].get(str(t['quest']), {}).get('area') for t in e['teams'].values() if t['quest']}
        quests = [self.catalog['tasks'].get(str(q)) for q in set(e['quests'].values()) if not cfg['quests'] or q in cfg['quests']]
        candidates = [(q, choose_members(q, roles, cfg['faith_min'], self.catalog.get('npcs', {}))) for q in quests
                      if q and duration(q, lv) > cfg['min_hours'] * 3600
                      and q['difficulty'] <= lv['difficulty'] and q['area'] not in occupied_areas]
        candidates = [(q, team) for q, team in candidates if team and
                      success_details(q, team, self.catalog.get('npcs', {}))['percent'] >= cfg['min_success']]
        if not candidates:
            e['status'] = f"沒有符合條件、預計超過 {cfg['min_hours']:g} 小時且成功率至少 {cfg['min_success']:g}% 的隊伍"
            return []
        quest, roles = max(candidates, key=lambda pair: (
            success_details(pair[0], pair[1], self.catalog.get('npcs', {}))['points'], duration(pair[0], lv), -pair[0]['id']))
        for role in roles:
            target = max(cfg['faith_min'], quest['faith_cost'])
            if role['faith'] >= target: continue
            packet = self.restore(state, role, target, cfg['item_id'], now)
            return [packet] if packet else []
        w = Writer().u16(quest['id'])
        members = [r['npc_id'] for r in roles]
        for npc in members + [0] * (4 - len(members)): w.u16(npc)
        w.u8(0)  # no support/shortening items
        self.pending = {'kind': 'dispatch', 'quest': quest['id'], 'members': members, 'due': now + 20}
        rate = success_details(quest, roles, self.catalog.get('npcs', {}))['percent']
        e.update(pending='dispatch', status=f"已送出任務 {quest['id']}（預估成功率 {rate:g}%），等待伺服器確認")
        return [Packet(31, 15, w.build())]

    def claim(self, state, team, now):
        e = state.expedition
        quest = self.catalog['tasks'].get(str(team['quest']), {})
        needed = claim_space(quest)
        inv = state.inventory
        if needed is None:
            e['status'] = '缺少此任務的獎勵容量資料，暫停自動領獎'
            return []
        capacity = inv.get('capacity')
        if (not inv.get('ready') or not inv.get('reliable') or type(capacity) is not int
                or not 1 <= capacity <= 255):
            e['status'] = '等待可靠的背包容量與物品資料，暫停自動領獎'
            return []
        free = sum(str(i) not in inv['items'] for i in range(1, capacity + 1))
        if free < needed:
            e['status'] = f'領獎需要至少 {needed} 格空間，目前僅 {free} 格；清出空間後自動繼續'
            return []
        self.pending = {'kind': 'claim', 'index': team['index'], 'quest': team['quest'],
                        'before': item_totals(inv), 'due': now + 20}
        e.update(pending='claim', status=f"已送出隊伍 {team['index']} 領獎，等待伺服器與物品入包確認")
        return [Packet(31, 16, Writer().u8(team['index']).build())]

    def restore(self, state, role, target, item_id, now):
        e = state.expedition
        inv = state.inventory
        if not inv.get('ready') or not inv.get('reliable'):
            self.stop(state, '背包資料尚不可靠，請等待同步後重新啟動')
            return None
        stock = recovery_stock(inv)
        deficit = target - role['faith']
        if item_id == 0:
            if sum(faith_gain(sid) * amount for sid, amount in stock.items()) < deficit:
                self.stop(state, '背包內可用的好友度恢復物品不足，已停止自動派遣')
                return None
            options = []
            for sid, amount in stock.items():
                gain = faith_gain(sid)
                required = math.ceil(deficit / gain)
                if amount >= required:
                    options.append((required, required * gain - deficit, sid))
            if options:
                item_id = min(options)[2]
            else:
                # Mix types sequentially, waiting for each batch's confirmation.
                item_id = max(stock, key=lambda sid: (faith_gain(sid) * stock[sid], -sid))
                target = min(target, role['faith'] + faith_gain(item_id) * stock[item_id])
        gain = faith_gain(item_id)
        if not gain:
            self.stop(state, '指定物品不是可用的好友度恢復物品')
            return None
        count = math.ceil((target - role['faith']) / gain)
        slots = {}
        remaining = count
        for index, item in sorted(inv['items'].items(), key=lambda pair: int(pair[0])):
            if item['item_id'] != item_id or item.get('locked') or item.get('limited_time', 0) or item.get('available_time', 0): continue
            used = min(available(inv, index), remaining)
            if used:
                slots[index] = (copy.deepcopy(item), used)
                remaining -= used
            if not remaining: break
        if remaining or len(slots) > 255:
            self.stop(state, '好友度恢復物品不足，已停止自動派遣')
            return None
        w = Writer().u8(role['index']).u8(len(slots))
        for index, (_, used) in slots.items(): w.u8(1).u16(int(index)).u16(item_id).u16(used)
        reservations.acquire(state.inventory,'expedition',[{'index':int(index),'item_id':before['item_id'],'count':used}
                             for index,(before,used) in slots.items()],exclusive=True)
        self.pending = {'kind': 'faith', 'index': role['index'], 'npc_id': role['npc_id'],
                        'target': target, 'slots': slots, 'consumed': dict.fromkeys(slots, 0),
                        'faith_ok': False, 'due': now + 20}
        e.update(pending='faith', status=f"補充夥伴 {role['npc_id']} 好友度：使用 {count} 個物品，等待確認")
        return Packet(31, 27, w.build())
