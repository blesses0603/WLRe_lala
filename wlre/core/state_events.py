"""Route each event to one local state domain after all service observers.

No network I/O, no UI interaction, no mutation of thread ownership here.
"""
from wlre.core.state_world_events import WORLD_KINDS, apply_world_event
from wlre.core.state_battle_events import BATTLE_KINDS, apply_battle_event
from wlre.core.state_session_events import SESSION_KINDS, apply_session_event

if (WORLD_KINDS & BATTLE_KINDS or WORLD_KINDS & SESSION_KINDS
        or BATTLE_KINDS & SESSION_KINDS):
    raise RuntimeError('State event handlers overlap')


def dispatch_local(state, event, *, affects_navigation):
    kind = event['type']
    if kind in WORLD_KINDS:
        apply_world_event(state, event, affects_navigation)
    elif kind in BATTLE_KINDS:
        apply_battle_event(state, event)
    elif kind in SESSION_KINDS:
        apply_session_event(state, event)
