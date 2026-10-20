"""Shared activity gates. A pause preserves intent; only explicit stops disable it.

Acknowledgements and timeout handling must run BEFORE these gates. Expedition
ignores auto-battle/roaming intent, but waits for actual combat or shared bag use.
"""
STOP_COMMANDS=frozenset(('stop_auto_battle','stop_roaming','stop_walk','stop_expedition',
                         'stop_crafting','stop_alchemy','chat','reset_efficiency'))
CRAFT_CONFLICTS=frozenset(('start_roaming','start_alchemy',
                         'field_item','field_storage','learned_action','battle_item'))


def active(value):return bool(value.get('pending') or value.get('uncertain'))
def craft_busy(state):return active(state.crafting) or state.crafting.get('auto_continue')
def expedition_busy(state):return active(state.expedition) or state.expedition.get('enabled')


def command_reason(state,command,*,maintenance_pending=False,maintenance_uncertain=False):
    kind=command.get('type')
    # Stopping continuation cannot cancel an outstanding request or its holds.
    if kind in STOP_COMMANDS or kind=='craft' and command.get('action') in ('stop_auto','plan_pause'):return ''
    if maintenance_pending or maintenance_uncertain or active(state.maintenance):
        return '請先等待戰後修理／整理確認；結果未確認時需重新登入同步'
    if expedition_busy(state) and kind in ('start_alchemy','craft','companion'):
        return '請先停止遠征自動派遣，並等待目前遠征操作確認'
    if kind in CRAFT_CONFLICTS and craft_busy(state):
        return '請先停止製作接續，並等待目前製作操作回覆'
    if kind=='allocate_points' and (state.battle.get('active') or state.event_flow.get('blocked')
            or state.roaming.get('enabled')):
        return '戰鬥、事件或自動移動中不可配點，請先等待或停止移動'
    return ''


def reason(state,service):
    """Return a temporary pause reason, without disabling any service."""
    if service in ('auto_battle','roaming','expedition','alchemy','crafting') and active(state.maintenance):
        return '等待戰後修理／整理確認'
    if service=='auto_battle':return ''
    if service=='roaming':
        supply=state.inventory.get('field_supply',{})
        if (state.maintenance.get('checking') or state.event_flow.get('blocked') or active(supply)
                or state.auto_battle.get('status') in ('healing','waiting_heal')):
            return '等待事件／補給完成'
        return ''
    if service in ('expedition','maintenance') and state.phase!='world_ready':return '等待登入與角色同步'
    if state.battle.get('active') or state.event_flow.get('blocked'):return '等待戰鬥／伺服器事件結束'
    if state.battle_count and state.battle.get('post_event',{}).get('status')!='completed':return '等待戰後事件完成'
    if state.activities:return '請先結束目前活動'
    if service=='maintenance':
        if craft_busy(state) or state.alchemy.get('enabled') or active(state.alchemy):return '等待製作／煉金完成'
        if active(state.expedition):return '等待遠征操作確認'
    elif service in ('expedition','alchemy'):
        if craft_busy(state):return '請先停止製作並等待回覆'
        if service=='expedition' and (state.alchemy.get('enabled') or active(state.alchemy)):
            return '請先停止煉金並等待回覆'
        if service=='alchemy' and active(state.expedition):return '等待遠征操作確認'
    elif service=='crafting':
        if expedition_busy(state):return '請先停止遠征自動派遣，並等待目前遠征操作確認'
        if state.alchemy.get('enabled') or active(state.alchemy) or state.roaming.get('enabled'):
            return '請先停止煉金或徘徊'
    if active(state.inventory.get('field_supply',{})):return '請先等待補給結果確認'
    return ''
