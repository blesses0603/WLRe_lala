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

This verifies shared-core offline behavior only. Full service composition, UI
presentation, live session acceptance and cross-platform device testing remain
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

### Explicit current-knowledge projection

`EfficiencyKnowledgeProjector.Project(updatedPlayer, updatedCompanions,
postLocalPlayer, npcNames)` requires the complete current player/companion
knowledge snapshots. Both snapshots and their required nested values are
validated, never defaulted to empty. `postLocalPlayer` may be null when local
identity is unknown. Its role and name are used after local dispatch, not copied
from a pre-local role context or from a stale role-list entry.

The projector copies only the evidence efficiency consumes:

- Player EXP, level, and degree come from current `PlayerKnowledgeSnapshot.Stats`.
  Missing keys remain null. Readiness does not filter confirmed observations.
- Every current companion dictionary entry is retained, including slot 0 and
  NPC identity 0. EXP/level/degree overrides take precedence over original S15
  values, including zero and negative overrides. Missing overrides use the S15
  fields. The original S15 name remains the confirmed name.
- Companion names follow the existing tracker priority: confirmed name,
  explicitly supplied NPC-name lookup, then slot fallback. The optional lookup
  is read and detached during projection, not retained or implicitly loaded.
- An empty explicitly supplied companion snapshot means no currently known
  companions. The projector does not manufacture emptiness, claim readiness, or
  decide whether a partial caller snapshot is complete.

Two previously documented representation gaps are now corrected:

- `default(EfficiencySubject)` and `EfficiencySubject.Player` remain self.
  `Companion(0)` is a distinct value/key with text `follow:0`, never an alias for
  self. Companion subjects accept the UInt16 S8 slot domain 0..65535; unknown
  slots cannot create rows without knowledge. Real S15-8 index 0 can create a
  row and receive EXP. Proven battle participants **still** require 1..255,
  exactly as Python does. A slot-zero EXP update can be dirty and sampled even
  though its missing EXP does not invalidate the baseline as a participant.
- `EfficiencyStats` and row level, degree, confirmed labels, and sample degree
  retain signed Int64 evidence. Valid S8-1 payload `2301ffffffff00000000` records
  level 4,294,967,295; `2701ffffffff00000000` records that degree. Their negative
  forms also survive. No cast/clamp/drop substitutes another label. Companion
  curve inference can still supply an explicitly flagged inferred label while
  the separate confirmed label retains the original wide value.

Existing Int32 curve helper signatures remain available. Int64 overloads reject
unsupported domains before narrowing/indexing the fixed curve cache. Unknown
curve values remain unknown; the wider labels do not extend the curve domain.
Existing numeric calls continue to compile, while consumers explicitly storing
row/knowledge label properties in `int?` must now preserve them as `long?`.

The projector is a read-only adapter, not a new authoritative knowledge store.
Production coordination must retain each actual receive reducer's returned
snapshots, dispatch local state once, then project and observe efficiency using
the post-local identity. No shared coordinator, session, or transport is changed
by this increment.

### Additional verification

```sh
WLRE_DISABLE_AUTO_CATALOG=1 python dotnet/Lala.Core.Tests/Battle/EfficiencyReceiveGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~Efficiency
```

Every original observer sequence now also runs through the immutable reducer,
including repeated snapshot rechecks after later transitions. Eleven additional
retained-decoder / `apply_live` / efficiency sequences provide 166 checkpoints.
Six retain the original explicit-knowledge receive-adapter coverage. Five also
run retained `dispatch_local` and compare the actual C# receive/local slices plus
knowledge projector before efficiency observation. Coverage includes slot zero,
unknown UInt16 slots, wide S8 labels and sample degree, buffered overrides,
same/different NPC replacement, post-local role/name changes, malformed packets,
wrong ownership/filters, star Int64 extremes, refresh removal, nonfinite times,
and completion boundaries. Both projected knowledge and efficiency snapshots
are rechecked after subsequent events. This focused harness is not a production
service coordinator or a claim that all service observers are composed.
Fixture time is explicit and the retained Python fallback is patched to a fixed
value, never measured from the host. New fixtures use the existing deterministic
gzip **byte-literal** helper and byte-only CRLF-normalized source SHA-256 checks.
Contract tests cover detached branching, thrown clocks after candidate role
reset, invalid typed payloads, subject range rejection, input validation, lazy
clocks, and nested publication immutability. Projector contracts also cover
Int64 extrema, source-limited participants, distinct self/slot-zero identities,
unknown slots, confirmed versus inferred wide labels, override precedence,
readiness-independent observations, nullable identity, catalog detachment,
complete membership, and strict rejection of missing required snapshots.

Remaining gates: integrated service observer-order/rollback tests, real resources,
runtime sessions, platforms/devices and official-server behavior.
This receive foundation does no game I/O or command transmission.
