# Offline completed-battle EXP efficiency

This increment ports `wlre/core/efficiency.py`, including its local ownership and
missing-evidence semantics, without wiring a live session, UI, resource loader,
or command sender. Python is retained unchanged.

## Input and publication contract

- `EfficiencyKnowledgeSnapshot` contains detached, confirmed knowledge **after**
  ordinary state reducers handle the event. The tracker is single-owner; publish
  its immutable `EfficiencySnapshot` to readers rather than sharing the tracker.
- Battle units prove local role/master ownership. Companion slot identities must
  already exist in knowledge. Unknown identity cannot create or update a row.
- Feed absolute character EXP (`kind=36`, `parameter=0`, `human_kind=4` for
  companions), star EXP, battle start, and event end through the typed events.
  `EfficiencyRefresh` models other events that only refresh known data. Winning
  or fight exit alone does not confirm completion.
- `ObservedAt` uses monotonic seconds or recorded offline timestamps. If absent,
  the injected clock is used. Zero is valid. Nonfinite times are ignored after
  any role-identity reset and before offline flags, row refresh, or completion.
- Catalog-derived names are optional injected presentation data. No catalog is
  loaded implicitly. `Reset()` corresponds to resetting the efficiency state;
  call `Observe` afterward to seed current knowledge, as the Python command does.
- Confirmed level/degree remain separately available in `ConfirmedLevel` and
  `ConfirmedDegree`; `Level`/`Degree` may carry explicitly flagged curve inference
  for companions. Player level/degree are never inferred.

## Preserved behavior

The first valid completed battle establishes a baseline. Missing participant EXP
invalidates only that participant's next gain baseline, retaining confirmed
historical rates. It is not a zero-EXP sample, and idle companion history survives.
Out-of-battle rewards rebase EXP without adding earned EXP. Stage changes, identity
changes and backwards totals reset the appropriate series. Repeated/backwards
timestamps suppress the gain and clear the rolling history without rewriting
previous all-time counters. Only 31 cumulative history points are kept, providing
10/30-interval windows; all-time counters are not capped.

The source's inclusive progress upper bound, maximum-level rules, level-one
cumulative origin, and negative-total companion-inference clamp are preserved.
An inferred label does not claim a server-confirmed level. Typed curve methods
return unknown for levels outside 1..400 or unsupported degrees; actual progress
caps are 199, 190 and 100. Character EXP uses signed 64-bit values, matching the
wire total. Earned EXP and gains use `BigInteger`, avoiding wraparound across
multiple large gains. Forecast text matches the Python helpers, including their
nonfinite and elapsed-time behavior.

## Verification

Regenerate the checked-in vectors from the retained Python observer (real `State`
and ownership wrappers, synthetic data only):

```sh
WLRE_DISABLE_AUTO_CATALOG=1 python dotnet/Lala.Core.Tests/Battle/EfficiencyGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~Efficiency
```

Differential evidence covers all 1,200 integer degree/level curve pairs, 373
progress cases, 17 duration cases, 150 forecasts, and complete sequences covering
identity/stage corrections, quest EXP, missing/idle participants, inference,
completion boundaries, 31-point rollover, reset, absent identity, late degree
knowledge, signed-64-bit extremes, zero/nonfinite/backward and extreme finite
times. Every generated checkpoint is also rechecked after later observations and
reset, detecting nested snapshot mutation. Contract tests additionally cover
injected clocks, confirmed/inferred evidence, unknown slots, detached input
collections, and immutable output dictionaries.

This verifies shared-core offline behavior only. Protocol-to-event integration,
UI presentation, live session acceptance and cross-platform device testing remain
outside this increment.

## Immutable receive foundation

`EfficiencySnapshot.Empty` and `EfficiencyReducer.Apply(snapshot, knowledge, event)`
provide an immutable alternative to the existing single-owner tracker. Each call
clones only mutable owner containers/scalars, then runs the **same** tracker
calculations. Immutable row/history values can be shared safely. Stage the result
with other domains and publish it only when the entire owning observation succeeds.
Thrown clocks, failed event adaptation, and discarded candidates cannot change the
input or earlier snapshots. An explicit reset uses `EfficiencySnapshot.Empty`.
Existing `EfficiencyTracker` construction, `Observe`, `Snapshot`, and `Reset`
semantics are unchanged.

The default reducer overload requires `event.ObservedAt` for an eligible role.
The overload taking `Func<double>` uses that explicit clock only when time is
absent. It never silently falls back to wall or process time. Role null/zero skips
observation before time access; a changed nonzero role resets before a nonfinite
time is ignored, matching Python. A thrown clock instead rejects the staged
observation atomically, including that candidate reset.

`EfficiencyReceiveReducer.Apply(snapshot, completeKnowledge, serverEvent,
observedAt, offline)` adapts decoded `ServerEvent` values and calls the immutable
reducer. `Adapt` is also exposed separately. Only battle start, event end, star
EXP, and eligible absolute S8 EXP have specialized events. Every other decoded
event becomes `EfficiencyRefresh`, including winner, fight exit, battle units,
non-EXP/parameterized S8, remote player attributes, and unsupported events.
Refresh still updates names/stats, removes absent companion rows, and handles
role/offline changes. It is **not** a no-op or battle completion. Failed packet
decoding must not call this observer.

The adapter requires complete detached knowledge after `apply_live`, using local
role/name **after** `dispatch_local`. It does not invoke those reducers, infer
readiness, select a role, or manufacture an empty player/companion projection.
No coordinator has been changed or marked complete by this increment.

### Explicit knowledge model gates

There is deliberately no automatic `PlayerKnowledgeSnapshot` /
`CompanionReceiveSnapshot` projector yet. Two existing efficiency input-model
limits must be resolved before general service composition:

- `EfficiencySubject` reserves slot 0 for the player and accepts companion slots
  1..255. The real S15-8 decoder reads an unrestricted byte slot: slot 0 is valid
  decoded data. Retained `set_companion` stores it under knowledge key `"0"`, and
  `efficiency._row` creates a distinct `"follow:0"` row. The explicit 1..255 check
  in Python applies to **battle participants**, not row identity. The current
  typed subject cannot represent this distinction. Eligible S8 companion EXP
  outside 1..255 is rejected by the adapter, never aliased to self or narrowed.
- Confirmed efficiency level/degree use `int?`, while current knowledge stores
  signed 64-bit S8 values. Valid S8-1 payload `2301ffffffff00000000` decodes level
  4,294,967,295; `2701ffffffff00000000` decodes degree 4,294,967,295. Retained
  `apply_live` and efficiency preserve these exact labels. Negative signed S8
  values can likewise fall below Int32. Do not cast, clamp, omit, or silently
  replace that evidence when adding the future projector.

Any future projector must use current companion stat overrides over original
S15 fields, complete companion membership, post-live player stats, and post-local
player identity/name. Optional catalog names remain explicit presentation inputs.
These gates are not permission to substitute a partial knowledge snapshot.

### Additional verification

```sh
WLRE_DISABLE_AUTO_CATALOG=1 python dotnet/Lala.Core.Tests/Battle/EfficiencyReceiveGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~Efficiency
```

Every original observer sequence now also runs through the immutable reducer,
including repeated snapshot rechecks after later transitions. Six additional
retained-decoder / `apply_live` / efficiency sequences provide 92 checkpoints
for the receive adapter, including malformed packets, wrong ownership/filters,
star Int64 extremes, refresh identity/name/removal, role zero/absence/reset,
nonfinite times, and completion boundaries. They supply the full resulting
knowledge explicitly; they do not claim C# knowledge projector/coordinator parity.
Fixture time is explicit and the retained Python fallback is patched to a fixed
value, never measured from the host. New fixtures use the existing deterministic
gzip **byte-literal** helper and byte-only CRLF-normalized source SHA-256 checks.
Contract tests cover detached branching, thrown clocks after candidate role
reset, invalid typed payloads, subject range rejection, input validation, lazy
clocks, and nested publication immutability.

Remaining gates: fix the two knowledge representations, add source-accurate
projection and integrated service observer-order/rollback tests, and then verify
real resources, runtime sessions, platforms/devices and official-server behavior.
This receive foundation does no game I/O or command transmission.
