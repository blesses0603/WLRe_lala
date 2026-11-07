# Offline local state composition

Sources: `wlre/core/state_events.py:dispatch_local`, the increment-before-dispatch
and position helper subset of `wlre/core/state.py`, and
`wlre/network/state_updates.py:StatePublisher`. This is **not the full State.apply
service-observer pipeline** or a replacement account/network session.

## Contract

`LocalStateCoordinator` composes the existing immutable session, world and battle
reducers. Construct it on the writer thread. `Apply(Packet)` decodes against the
current world player identity before applying; `Apply(ServerEvent)` accepts an
already decoded observation. `Apply(BattleCommandSentEvent)` records only an
already-successful send observation and never sends a command.

Each non-null observation increments packet count once before local dispatch,
including ignored, unsupported, and malformed-S51 metadata observations. A strict
packet-decoder exception occurs before the counter changes. A synthetic typed
observation rejected by a reducer has already incremented the counter, but the
immutable reducer cannot publish a partial domain update. Python's arbitrary
malformed dictionaries and their partial-write behavior are not modeled.

All Python local route kinds are covered. Only one domain runs per event.
Detailed S62-1/2/4/5/76 furniture observations wrapped in `ServerInventoryEvent`
retain their `navigation_geometry_change` meaning in both the world reducer and
coordinator. House scope is checked against explicit catalog evidence; unknown
scenes conservatively invalidate. An empty S62-4 snapshot neither invalidates nor
clears earlier staleness. Other inventory and crafting observations remain local
no-ops; their service observers are not invoked.
Session/world phase and packet-count projections remain equal. Battle ownership
always uses the current `World.Player.RoleId`; roles, account IDs and battle slot
occupants do not become local identity. Role-list and login events retain the
existing world player and battle observations, exactly like local Python dispatch.
No additional reconnect/reset behavior is inferred.

The world helpers run on the same owner and do not increment packet count.
`LocalStateSnapshot` reuses typed immutable projections. If only the session or
world projection is supplied, the other inherits shared phase/count values.
Supplying both with conflicting values is rejected rather than silently losing
state. Captured snapshots are safe to retain/read on other threads; the coordinator
and publisher remain owner-thread only. The catalog parameter is explicit caller
input, not resource activation or a navigation authorization.

`LocalStatePublisher` is synchronous: applying events never waits for publication.
The first or forced publication runs immediately. A later publication is pending
until the interval since the **post-callback** timestamp has elapsed. `Flush` only
attempts a pending publication and does not force it. Callback/clock errors escape,
leaving pending true and the previous completed timestamp. There is no timer,
queue, asynchronous dispatch, observer loop or lifecycle notification hook.

## Differential evidence

```sh
python dotnet/Lala.Core.Tests/State/LocalStateGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~LocalState
```

The generator invokes retained Python `dispatch_local`, actual packet decoders,
State helpers and `StatePublisher`. It does not invoke service observers. It asserts
that the event sequences cover every Python WORLD/BATTLE/SESSION kind. Nine
sequences have 283 checkpoints, including five seeded 40-step interleavings;
all earlier snapshots are rechecked after the final event. Four publisher traces
cover 23 operations with forced updates, empty/pending flush, boundary timing,
callback elapsed time, clock regression and callback exceptions. Ten additional
contract tests cover owner threads, invalid inputs, count ownership, immutable
publications, explicit catalog isolation and post-callback clock failures.

The local-state generator stores the same JSON cases in deterministic gzip/base64
form to keep review files small; decompressing preserves every case byte-for-byte.
`World/FurnitureGeometryGenerateVectors.py` adds 21 packet-level scenarios / 468
Python checkpoints through both the standalone world reducer and coordinator,
plus seven integration contract cases for strict malformed decoding and service
isolation. These cover detailed furniture, shallow geometry fallbacks, known and
unknown scenes, validated/unverified aliases, empty snapshots, history bounds,
scene changes and retained snapshots.

## Explicit gaps

No socket/frame stream or cancellation API, AccountSession changes, reconnect,
login lifecycle, service observers, automatic candidate requests, inventory,
command authorization, UI/Android binding, or official-server acceptance. Existing
reducer limitations still apply. The Python `notify_state` polymorphic callback
adapter is not needed or ported: callers explicitly choose direct snapshots or the
local coalescing publisher. No persistent state or credentials are introduced.
