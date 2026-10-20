"""1262 cooperative battle continuation with verified own-side evidence.

FightUnit:GetDirection maps columns 1..2 to Left, 3..4 to Right.
FightManager.RevWinner marks Right winner=1 and Left winner=2.
"""


def own_victory(state):
    side = state.battle.get('winner_side')
    pid = state.player.get('role_id')
    if type(side) is not int or side not in (1, 2) or not pid:
        return None
    columns = {unit.get('col') for unit in state.battle_units.values()
               if unit.get('pid') == pid and type(unit.get('col')) is int}
    if len(columns) != 1:
        return None
    col = next(iter(columns))
    return side == (1 if col > 2 else 2) if 1 <= col <= 4 else None


def consume_coop_fight(state):
    """Return official post-fight delay; unknown fight count uses normal 2.5s.

    The 1262 client checks whether FightCount > 1. A missing S186-15
    is not evidence that a new cooperative match should be started,
    but it must not suppress FightManager.SendServerEvent indefinitely.
    """
    data = state.instances['coop']
    battle_id = state.battle_count
    if data.get('fight_consumed_battle') == battle_id:
        return None
    count = data.get('fight_count')
    if type(count) is not int or count < 1:
        # Official CheckFightCount() returns false for the default count=0;
        # FightOver() then calls SendServerEvent() after the normal exit delay.
        # Preserve the unknown state and do not speculate on a victory/next fight.
        data['fight_consumed_battle'] = battle_id
        data['last_fight_victory'] = None
        return 2.5
    data['fight_consumed_battle'] = battle_id
    data['fight_count'] = count - 1
    won = own_victory(state)
    data['last_fight_victory'] = won
    return 5.0 if count > 1 and won is True else 2.5
