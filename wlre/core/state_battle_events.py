"""Battle state changes with no speculative damage or HP calculations."""
BATTLE_KINDS = frozenset((
    'battle_start', 'battle_units', 'battle_attribute_set', 'round_start',
    'battle_unit_exit', 'fight_exit', 'battle_command_sent', 'attack_result',
    'war_style', 'winner',
))


def apply_battle_event(state, event):
    kind = event['type']
    if kind in ("battle_start", "battle_units"):
        if kind == "battle_start":
            state.battle_count += 1
            state.battle_units.clear()
            state.battle = {"actions": 0, "winner_side": None, "round": 0,
                           "stage": event["stage"], "fight_number": event["fight_number"], "active": True, "commands": {}}
        for unit in event["units"]:
            state.battle_units[f"{unit['col']}:{unit['row']}"] = dict(unit)
    elif kind == "battle_attribute_set":
        for value in event["values"]:
            unit = state.battle_units.get(f"{value['col']}:{value['row']}")
            if unit is not None:
                unit.setdefault("attributes", {})[str(value["kind"])] = value["value"]
                if value["kind"] == 25: unit["hp"] = value["value"]
                elif value["kind"] == 26: unit["sp"] = value["value"]
    elif kind == "round_start":
        if state.battle.get("round") != event["round"]:
            state.battle["commands"] = {}
        state.battle["round"] = event["round"]
    elif kind == "battle_unit_exit":
        unit = state.battle_units.get(f"{event['col']}:{event['row']}")
        if unit is not None:
            unit["exited"] = True
            if unit.get('pid')==state.player.get('role_id'):state.battle['active']=False
    elif kind == "fight_exit" and event["role_id"] == state.player.get("role_id"):
        state.battle["active"] = False

    if kind == "battle_command_sent":
        state.battle.setdefault("commands", {})[f"{event['col']}:{event['row']}"] = {**event, "status":"sent"}
    elif kind == "attack_result":
        state.battle["actions"] += len(event["actions"])
        state.battle["last_actions"] = event["actions"]
        for action in event["actions"]:
            entry=state.battle.get("commands",{}).get(f"{action['col']}:{action['row']}")
            if entry:entry["status"]="resolved"
        # 50-1 alone lacks slot-to-role mapping, shield state and initial HP.
        # Keep reported changes; do not incorrectly subtract from role HP.
    elif kind == "war_style":
        state.battle["war_style"] = event["value"]
    elif kind == "winner":
        state.battle["winner_side"] = event["side"]
        state.battle["active"] = False
