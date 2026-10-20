"""Login, blocking events, raw S8 values and unimplemented counters."""
SESSION_KINDS = frozenset((
    'login_result', 'role_list_available', 'movement_stop', 'event_active',
    'event_continue_permission', 'event_end', 'initial_data_complete',
    'attribute_set', 'unimplemented', 'event_rejected',
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
        effect=event.get('npc_effect')
        if effect is not None:
            if state.npc_dialogue.get('active'):
                effect_type=effect['effect_type']
                talk_history=list(state.npc_dialogue.get('history') or [])
                if effect_type == 1 and type(effect.get('mean_number')) is int:
                    talk_history.append(effect['mean_number'])
                    talk_history=talk_history[-50:]
                state.npc_dialogue={**state.npc_dialogue,
                    'history':talk_history,
                    'phase': ('talk' if effect_type==1 else
                              'choice_unavailable' if effect_type==6 else 'effect_unavailable'),
                    'effect_type':effect_type,
                    'text_id':effect['mean_number'] if effect_type==1 else None,
                    'option_index':effect['mean_number'] if effect_type==6 else None}
            else:
                state.npc_dialogue={**state.npc_dialogue,'last_effect':effect}
        elif state.npc_dialogue.get('active'):
            state.npc_dialogue={**state.npc_dialogue,'phase':'effect_unavailable'}
        state.event_flow={**state.event_flow,'blocked':True,'awaiting_response':False,
                         'last_source':f"S20-{event['sub']}（事件處理尚未完成）"}
    elif kind == 'event_continue_permission':
        state.event_flow={**state.event_flow,'blocked':True,'awaiting_response':False,
                         'last_source':f"S20-{event['sub']}"}
        if (state.npc_dialogue.get('active')
                and state.npc_dialogue.get('phase') in ('requesting','awaiting_reply')):
            state.npc_dialogue={**state.npc_dialogue,'phase':'continue'}
    elif kind == 'event_end':
        state.event_flow={**state.event_flow,'blocked':False,'awaiting_response':False,'last_source':'S20-8'}

        if state.npc_dialogue.get('active'):
            state.npc_dialogue={**state.npc_dialogue,'active':False,'phase':'ended'}
    elif kind == 'event_rejected' and state.npc_dialogue.get('active'):
        state.event_flow={**state.event_flow,'blocked':False,'awaiting_response':False,
                          'last_source':'S20-74'}
        state.npc_dialogue={**state.npc_dialogue,'active':False,'phase':'rejected','reason':event.get('reason','')}
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
