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
