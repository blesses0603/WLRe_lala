"""Atomic controls and a read-only view over existing daily services.

This module owns no timer, protocol packets, completion or spending ledger.
The service schedulers remain the sole authority for executing enabled work.
"""
from copy import deepcopy
from types import SimpleNamespace

from wlre.network.wire import ProtocolError
from wlre.services import daily_tasks, star_ark, time_cube
from wlre.services.social import guild_actions


FIELDS = {
    'time_cube': {'cube_enabled': 'enabled'},
    'daily_tasks': {'rewards_enabled': 'enabled'},
    'guild_actions': {'guild_sign_enabled': 'sign_enabled',
                      'guild_donate_enabled': 'donate_enabled',
                      'gold_budget': 'budget', 'guild_target': 'target',
                      'guild_sell_id': 'sell_id'},
    'star_ark': {'ark_dispatch_enabled': 'dispatch_enabled',
                 'ark_fights_enabled': 'fights_enabled',
                 'ark_questions_enabled': 'questions_enabled',
                 'star_budget': 'budget', 'ark_hours': 'hours'},
}


def command(state, value, world_acknowledged, now=None):
    """Validate all requested settings on copies, then commit without packets.

    Unspecified fields/services are untouched. A stop always preserves pending
    requests and accounting; normal service ticks still process confirmations.
    """
    action = value.get('action')
    allowed = {'type', 'action'}
    if action == 'configure':
        allowed.update(key for fields in FIELDS.values() for key in fields)
        selected = [name for name, fields in FIELDS.items() if fields.keys() & value.keys()]
    elif action == 'stop':
        allowed.add('services')
        selected = value.get('services', list(FIELDS))
        if (not isinstance(selected, list) or not selected
                or any(not isinstance(name, str) or name not in FIELDS for name in selected)
                or len(set(selected)) != len(selected)):
            raise ProtocolError('每日助手停止項目無效')
    else:
        raise ProtocolError('未知的每日助手操作')
    if value.keys() - allowed:
        raise ProtocolError('每日助手包含未知設定')
    staged = SimpleNamespace(**{name: deepcopy(getattr(state, name)) for name in selected})
    for name in selected:
        data = getattr(staged, name)
        if action == 'configure':
            settings = {key: value.get(field, data[key]) for field, key in FIELDS[name].items()}
            if name == 'star_ark':
                toggles = ('dispatch_enabled', 'fights_enabled', 'questions_enabled')
                explicit_toggle = any('ark_' + key in value for key in toggles)
                if explicit_toggle and not data['enabled']:
                    # A paused master has no effective selected sub-actions.
                    for key in toggles:
                        if 'ark_' + key not in value:
                            settings[key] = False
                settings['enabled'] = (any(settings[key] is True for key in toggles)
                                       if explicit_toggle else data['enabled'])
            settings['action'] = 'auto' if name in ('time_cube', 'daily_tasks') else 'settings'
        else:
            settings = {'action': 'auto', 'enabled': False} if name in (
                'time_cube', 'daily_tasks') else {'action': 'pause'}
        if name == 'time_cube':
            packets = time_cube.command(staged, settings, now)
        elif name == 'daily_tasks':
            packets = daily_tasks.command(staged, settings, world_acknowledged, now)
        elif name == 'guild_actions':
            packets = guild_actions.command(staged, settings, world_acknowledged)
        else:
            packets = star_ark.command(staged, settings, world_acknowledged, now)
        if packets:
            raise ProtocolError('每日助手設定不得送出遊戲操作')
    # Only control fields are committed. Preserve original pending objects and
    # all reserved/confirmed/uncertain/generation evidence, even on repeat apply.
    for name in selected:
        data = getattr(staged, name)
        keys = set(FIELDS[name].values()) | {'status'}
        if name in ('guild_actions', 'star_ark'):
            keys.add('settings_revision')
        if name == 'star_ark':
            keys.add('enabled')
        getattr(state, name).update({key: data[key] for key in keys})
    return []


def _catalog_token(value):
    """Normalize only the official token's JSON tuple/list representation."""
    if (not isinstance(value, (tuple, list)) or len(value) != 2
            or type(value[0]) is not bool or not isinstance(value[1], str)
            or not value[1]):
        return None
    return tuple(value)


def _availability(state, service, subtype):
    """Use existing read-only guards plus observed quotes, never fetch a catalog."""
    data = state.get(service, {})
    try:
        snapshot = SimpleNamespace(**state)
        if service == 'time_cube':
            return time_cube.problem(snapshot)
        if service == 'guild_actions':
            issue = guild_actions.common_problem(snapshot)
            if issue:
                return issue
            if subtype == 1:
                return '' if data.get('sign_state') == 1 and not data.get('sign_attempted') else '等待可簽到狀態，或本期已送出簽到'
            if not data.get('catalog_ready'):
                return '等待同版組織消費資料'
            if not data.get('allow') or data.get('remaining') is None:
                return '等待捐獻資格與剩餘次數'
            if not data['remaining'] or (data.get('donated') is not None and data['donated'] >= data['target']):
                return '今日捐獻次數已達設定目標'
            price = data.get('price')
            currency = state.get('gold', {})
        else:
            issue = star_ark.problem(snapshot)
            if issue:
                return issue
            if not data.get('catalog_token'):
                return '等待同版方舟資料'
            if subtype == 1:
                if not data.get('events_ready'):
                    return '等待方舟事件清單'
                reasons = []
                for event in data.get('events', {}).values():
                    if not event.get('id'):
                        continue
                    kind = event.get('kind')
                    if not (kind == 1 and data.get('fights_enabled') or
                            kind == 3 and data.get('questions_enabled')):
                        continue
                    if event['main']:
                        reasons.append('主線事件僅供檢視，不自動推進主線')
                    elif event['planet'] > min(data['planet'], 20):
                        reasons.append('事件所在星球尚未開放')
                    elif list(star_ark._event_key(data, event, data['catalog_token'])) in [
                            list(attempt) for attempt in data['attempted']]:
                        reasons.append('此事件已要求執行，等待新事件清單')
                    elif kind == 1 and not state.get('auto_battle', {}).get('enabled'):
                        reasons.append('請先啟用並設定自動戰鬥')
                    else:
                        # Read only the already activated official catalog.
                        # Cached rows/quotes cannot prove current reward safety.
                        catalog, token, note = star_ark.runtime_catalog()
                        current = _catalog_token(token)
                        if not catalog:
                            reasons.append(note or '等待同版方舟資料')
                            continue
                        if (current is None
                                or _catalog_token(data.get('catalog_token')) != current
                                or _catalog_token(state.get('daily_tasks', {}).get('catalog_token')) != current):
                            reasons.append('等待同版方舟與每日任務資料')
                            continue
                        try:
                            if kind == 1:
                                star_ark.fight_rewards(snapshot, event, catalog)
                        except ProtocolError as exc:
                            reasons.append(str(exc))
                            continue
                        return ''
                return '；'.join(dict.fromkeys(reasons)) or '等待支援且已啟用的方舟事件；交付與商人需手動處理'
            quote = data.get('quote') or {}
            price = quote.get('price')
            currency = data.get('starcoin', {})
        if price is None:
            return '等待可驗證的消耗報價與執行資格'
        if data.get('reserved', 0) + price > data.get('budget', 0):
            return '已達金幣消耗上限' if service == 'guild_actions' else '已達星力消耗上限'
        if not currency.get('ready') or not currency.get('reliable') or currency.get('amount') is None:
            return '等待可靠的貨幣同步'
        if currency['amount'] < price:
            return '目前貨幣不足'
        return ''
    except (AttributeError, KeyError, TypeError):
        return '等待完整伺服器同步'


def view(state_dict):
    """Project a detached snapshot; only inspect active catalogs, never fetch them.

    Classifications describe automation coverage, not proof of task completion.
    Unknown conditions and unsupported actions remain manual.
    """
    state = deepcopy(state_dict)
    services = {}
    settings = {}
    defaults = {'time_cube': time_cube.defaults, 'daily_tasks': daily_tasks.defaults,
                'guild_actions': guild_actions.defaults, 'star_ark': star_ark.defaults}
    for name, fields in FIELDS.items():
        data = state.get(name, {})
        control_defaults = defaults[name]()
        settings.update({field: data.get(key, control_defaults[key]) for field, key in fields.items()})
        services[name] = {
            'enabled': (bool(data.get('sign_enabled') or data.get('donate_enabled'))
                        if name == 'guild_actions' else bool(data.get('enabled'))),
            'pending': deepcopy(data.get('pending')),
            'uncertain': bool(data.get('uncertain')),
            'status': data.get('status', '等待伺服器同步'),
        }
    if 'star_ark' in state and not services['star_ark']['enabled']:
        for key in ('ark_dispatch_enabled', 'ark_fights_enabled', 'ark_questions_enabled'):
            settings[key] = False
    daily = state.get('daily_tasks', {})
    rows = []
    for source in daily.get('rows', []):
        if source.get('cycle') != 1:
            continue
        row = deepcopy(source)
        kind = row.get('condition_kind')
        params = row.get('condition_params') or []
        subtype = params[0] if params else None
        service = None
        enabled = False
        note = '此條件需手動處理；助手不會代做'
        if kind == 16:
            service, enabled = 'time_cube', settings['cube_enabled']
        elif kind == 10 and subtype in (1, 2):
            service = 'guild_actions'
            enabled = settings['guild_sign_enabled' if subtype == 1 else 'guild_donate_enabled']
        elif kind == 9 and subtype in (1, 2):
            service = 'star_ark'
            enabled = (settings['ark_dispatch_enabled'] if subtype == 2 else
                       settings['ark_fights_enabled'] or settings['ark_questions_enabled'])
            enabled = enabled and services[service]['enabled']
            note = '僅支援已啟用的派遣／一般戰鬥／可確認答案；交付、商人與未知題目需手動處理'
        classification = 'manual'
        if row.get('received'):
            classification, note = 'progress', '伺服器已標記領取'
        elif service:
            info = services[service]
            if info['uncertain']:
                classification, note = 'blocked', info['status']
            elif (service == 'star_ark' and subtype == 1
                  and (info['pending'] or {}).get('kind') == 'question'
                  and state.get('star_ark', {}).get('question')
                  and state['star_ark']['question'].get('selected') is None
                  and state['star_ark']['question'].get('known_answer') is None):
                classification, note = 'manual', '此題沒有可確認答案，請到方舟分頁選擇答案'
            elif info['pending']:
                classification, note = 'progress', info['status']
            elif (not enabled or not state.get('automation', {}).get('enabled')
                  or not daily.get('ready') or not daily.get('groups_ready')
                  or not daily.get('catalog_ready')
                  or state.get('phase') != 'world_ready'):
                classification, note = 'blocked', '已暫停或等待角色／任務同步；' + info['status']
            else:
                issue = _availability(state, service, subtype)
                classification = 'blocked' if issue else 'automatic'
                if issue:
                    note = issue + '；' + info['status']
                else:
                    note = ('由既有流程再次檢查資格後執行；' if kind != 9 else note + '；') + info['status']
        elif kind == 1:
            classification, note = 'progress', '登入進度由伺服器記錄'
        row.update(classification=classification, reason=note, service=service)
        rows.append(row)
    budgets = {}
    for currency, name in (('gold', 'guild_actions'), ('star', 'star_ark')):
        data = state.get(name, {})
        budgets[currency] = {key: data.get(source) for key, source in
                             (('limit', 'budget'), ('reserved', 'reserved'), ('confirmed', 'confirmed'))}
    return {'settings': settings, 'rows': rows, 'services': services, 'budgets': budgets,
            'status': daily.get('status', '等待每日任務同步')}
