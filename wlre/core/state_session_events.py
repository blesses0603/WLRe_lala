"""Login, blocking events, raw S8 values and unimplemented counters."""
SESSION_KINDS = frozenset((
    'login_result', 'role_list_available', 'movement_stop', 'event_active',
    'event_continue_permission', 'event_end', 'initial_data_complete',
    'attribute_set', 'unimplemented',
))


def apply_session_event(state, event):
    kind = event['type']
    if kind == "login_result":
        state.phase = "authenticated" if event["result"] == 0 else "login_failed"
    elif kind == "role_list_available":
        state.phase = "role_selection"
        state.roles = event.get("roles", [])
    elif kind == 'movement_stop':
        state.event_flow={**state.event_flow,'blocked':True,'last_source':f"S6-2 kind={event['kind']}"}
    elif kind == 'event_active':
        state.event_flow={**state.event_flow,'blocked':True,'awaiting_response':False,
                         'last_source':f"S20-{event['sub']}（事件處理尚未完成）"}
    elif kind == 'event_continue_permission':
        state.event_flow={**state.event_flow,'blocked':True,'awaiting_response':False,
                         'last_source':f"S20-{event['sub']}"}
    elif kind == 'event_end':
        state.event_flow={**state.event_flow,'blocked':False,'awaiting_response':False,'last_source':'S20-8'}

    elif kind == "initial_data_complete":
        state.initial_data_complete = True

    if kind == "attribute_set":
        # Protocol 8 values are replacements, not deltas. Preserve param
        # because skill/skill-EXP updates use it as a separate namespace.
        entity = state.attributes.setdefault(event["entity"], {})
        key = f"{event['kind']}:{event['parameter']}"
        entity[key] = event["value"]

    if kind == "unimplemented":
        state.unimplemented_count += 1
