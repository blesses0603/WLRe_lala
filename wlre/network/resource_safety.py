"""Session-local resource hold, applied only by the network state owner.

A hold stops new intent at dispatch boundaries, not packets in an operation
already started. Pending requests, reservations and server confirmations stay
intact. Clearing the caller's Event never resumes this connection.
"""

HOLD_REASON = (
    '官方版本或資料庫身分尚未確認，已暫停新的資料依賴操作與事件接續；'
    '已送出要求仍等待伺服器確認，需重新連線後重新驗證。')


def hold_event():
    return {'type': 'resource_safety_hold', 'status': 'held', 'reason': HOLD_REASON}


def command_allowed(command):
    """Only data-independent chat and local stop controls remain available."""
    kind, action = command.get('type'), command.get('action')
    if kind in ('chat', 'stop_auto_battle', 'stop_roaming', 'stop_walk',
                'stop_expedition', 'stop_alchemy', 'reset_efficiency'):
        return True
    if kind == 'craft':
        return action in ('stop_auto', 'plan_pause')
    if kind == 'automatic_flows' or kind == 'instance_auto_reward':
        return command.get('enabled') is False
    if kind == 'daily_assistant':
        return action == 'stop'
    if kind in ('star_ark', 'guild_actions'):
        return action == 'pause'
    if kind in ('daily_tasks', 'time_cube'):
        return action == 'auto' and command.get('enabled') is False
    return False


def apply_hold(logic, state):
    """Latch once, preserving every in-flight service's pending evidence."""
    state.assert_writer()
    if logic.resource_safety_held:
        return True
    event = logic.resource_safety_hold
    if event is None or not event.is_set():
        return False
    logic.resource_safety_held = True
    logic.flows.set_enabled(state, False)
    logic.auto_battle.stop(state, HOLD_REASON, source='resource_safety')
    # Stopping AI also prevents new field supply and post-battle maintenance.
    logic.roaming.stop(state, logic.movement, HOLD_REASON)
    logic.expedition.stop(state, HOLD_REASON)
    logic.alchemy.stop(state, HOLD_REASON)
    # An unsent route can be canceled; a sent door request must retain its
    # deadline and event ownership until normal receive/timeout handling.
    if logic.portal_travel.deadline is None:
        logic.portal_travel.cancel(state, HOLD_REASON)
    from wlre.services.daily_assistant import command as daily_control
    daily_control(state, {'action': 'stop'}, logic.world_acknowledged)
    state.automation.update(resource_safety_hold=True, status=HOLD_REASON)
    return True


def observe_hold(logic, state):
    """Scheduler seam also supports older isolated service test fixtures."""
    check = getattr(logic, 'check_resource_safety', None)
    return bool(check(state)) if check is not None else False
