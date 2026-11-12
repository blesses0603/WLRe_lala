# Offline session-event reducer

This slice ports `wlre/core/state_session_events.py` to `SessionEventReducer.Apply`
using the existing typed `ServerEvent` hierarchy. It does not change
`AccountSession`, transport interfaces, Python code, command authorization,
credential storage, the desktop UI, or Android lifecycle behavior.

## State contract

`SessionEventSnapshot` is a small immutable projection, not the complete Python
`State`. Its defaults come from only the corresponding fields in `state.py`.
The caller owns packet counting: supply the already-current `PacketCount` before
calling `Apply`, just as `State.apply` increments before dispatching the Python
reducer. This matters for NPC `EffectPacket` evidence. The reducer never counts
packets, sends anything, grants permissions, or establishes `world_ready`.

All arrays and both levels of the attribute dictionary are immutable. Updates
preserve earlier snapshots. Counts and revisions use `BigInteger` to retain
Python's unbounded counter behavior. Balances use nullable `uint`; widening the
signed event delta before addition prevents even synthetic Int64 extremes from
wrapping into a trusted balance. Raw malformed Python dictionary values such as
boolean/string gold amounts or non-integer effect IDs are unrepresentable in the
typed models. Malformed **wire effects** are represented by `NpcEffectEvent` with
null details and remain blocking, matching the existing decoder and Python.
Absent optional Python fields normalize to null, empty history, or false pending.

Interaction identity (`Scene`, `NpcId`, `NpcIndex`, `SelectedChoice`) is carried
unchanged. It is not verified here and does not authorize interaction. Additional
Python State domains and arbitrary dictionary extensions are outside this typed
projection, rather than silently being treated as migrated behavior.

## Preserved transitions

- Login success/failure and role selection; role-list arrival resets only the
  gold evidence, phase and roles, not unrelated initialization/dialogue state.
- Absolute gold snapshots, readiness/reliability, pre-initialization deltas,
  limit invalidation, zero deltas, underflow/overflow, revision and recovery.
  Limit notices preserve the amount but make it unreliable; a subsequent delta
  cannot restore it. Only an authoritative snapshot recovers reliable evidence.
- Movement stops, event blocking, dialogue effects, inactive `LastEffect`, exact
  continuation phases, pending-choice invalidation, end and rejection. A rejected
  inactive dialogue cannot release another event's block. Talk history retains
  the last 50 entries; non-talk effects do not truncate existing history.
- S8 values replace the exact entity / `kind:parameter` key, including skill-EXP
  namespaces. Only `UnimplementedServerEvent` increments the unknown counter.
  Explicitly unsupported decoders and unrelated events remain no-ops.

## Verification

Regenerate the checked-in synthetic vectors with the retained Python reducer,
real `State` ownership wrappers, and existing Python wire decoder:

```sh
python dotnet/Lala.Core.Tests/Sessions/SessionEventGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~SessionEvent
```

There are 314 differential sequences with 1,589 checked state transitions:
all 256 NPC effect types; every 0..17-byte malformed effect prefix; active and
inactive effects; every continuation subcode and phase; repeated end/rejection;
50-item history rollover; role replacement/reset; all gold evidence combinations,
limits, range failures and recovery; nested attribute replacements; unknown
counts; and eight reproducible mixed-event replays. Every input is rechecked
immediately after reduction, and every published checkpoint is rechecked after
all later updates. Separate contract tests verify default immutable arrays,
detached builders, mutation rejection, typed dispatch, null arguments,
caller-owned packet counting, and discarded credential/extension bytes.

These are offline shared-core tests only. Live reducer dispatch, session
integration, commands, complete State parity, official-server acceptance, and
physical-device behavior remain outside this slice.

Generated sequences are partitioned into partial-class source files for bounded review units; the generator retains the same case order and all 1589 checkpoints.
