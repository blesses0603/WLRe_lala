# Receive-owned battle actors

`BattleUnitState.Actor` and `BattleEventSnapshot.Actors` project the current immutable
battle publication into combat resource observations. Consumers of receive
`Snapshot.Local.Battle` use the same committed state as the next receive observation.
No second store, runtime endpoint, scheduling, holds, sends, or catalog activation is added.
Entries preserve Python dictionary insertion order, including exited occupants.

Source mapping: `wlre/network/layouts.py: battle_unit`,
`wlre/core/state_battle_events.py: apply_battle_event`, and
`wlre/services/items/combat_resources.py: apply_live`.
Identity, appearance, element, level, degree, job and maxima originate in the layout.
Only S51 kinds 25/26 replace actor HP/SP. Kinds 46/47 update owned profile maxima,
but do not replace battle actor maxima. Other raw attributes are not inferred stats.
S11-252 replaces battle appearance even for a same-item design change; damage and
full item metadata remain unknown. No current decoder supplies fly/status evidence,
so the existing actor defaults remain false/empty. Attack reports do not infer vitals.
Replacement discards occupant overlays and exit state without moving its dictionary
position. A new battle start clears old entries. Retired publications remain historical
immutable evidence, not current runtime authority; a fresh empty attempt has no actors.

Existing retained Python battle vectors now also compare every actor field and historical actor projection at each transition. Tests cover sparse fields, explicit zero identity, current UInt32 vitals, original maxima,
design-only appearance, replacement/order/start, and a held, split-frame synthetic receive
sequence passing published actors to the existing detached chooser. The chooser test uses
explicitly synthetic empty catalogs and a defend action. It proves data compatibility,
not a production combat pipeline: OfflineRuntimeCandidate still lacks the Lua define/fight
constants required for complete combat/normal catalogs. Full catalog assembly and automatic
chooser scheduling remain separate unfinished work. No live server or credentials are used.
