# Offline world-event reducer

This slice ports the six branches in `wlre/core/state_world_events.py` and
`State.remember_position`, `clear_position_history`, `wait_for_position`, and
`confirm_location` into `WorldEventReducer` and immutable world snapshots. It
reuses the existing `ServerEvent`, `WorldPlayer`, `HouseFloorExtension`, and
wrapped layout/social events. It does not alter Python, `AccountSession`,
transport, lifecycle, UI, or the existing navigation/route implementations.

## State and authority contract

- `WorldEventSnapshot` projects only the world fields consumed by this reducer.
  `Player` retains the complete decoded S3 player. Local movement projects only
  status and target; arbitrary Python dictionary extensions are not ported.
- Packet counting belongs to the caller. Supply the already-current
  `PacketCount` as Python `State.apply` does before dispatch. Counters, revisions,
  and cache order stamps use `BigInteger`, preserving unbounded Python integers.
- S3 and own S7/S12 positions are authoritative. Movement requests and own S6
  walks only update destinations, waiting checks, and the observed cache. They
  do not overwrite authoritative player coordinates or confirm arrival.
- A local route in `running` or `finished` status supplies the preferred waiting
  target. Neither route status proves arrival. Waiting/different-position
  checks advance only for the same known role; matched/scene-changed checks do
  not reopen until a new wait. An identity change cannot resolve an old role's
  check. Confirmation clears both destination fields.
- The immutable cache is ordered oldest first and bounded to 2,048 entries.
  Refreshes move an entry to newest. On eviction, an oldest own slot moves to
  newest before the oldest remote slot is removed, exactly as Python does.
  Signed S6 IDs and unsigned S3/S7/S12 IDs widen to `long` without bit-pattern
  reinterpretation. Cache data is not authoritative local position evidence.
- Scene transitions and world-player replacement reset remote positions.
  Clearing history preserves the observed own cache entry, even when that
  entry is a destination rather than the last authoritative location.
- Geometry notices increment revision, mark stale, and retain only ten reasons.
  They do not rebuild geometry or infer a floor. As in Python, a notice does not
  itself rewrite `runtime_geometry_verified`; callers must respect `stale`.
  An own position resets that verification flag. Same-scene positions preserve
  stale/reasons, while scene changes and S3 replacement reset them.

## House context and injected catalog boundary

`WorldHouseContextRules.UpdateContext` ports `house_navigation.update_context`
for typed decoded extensions. It retains floor sizes only in the same verified
house context. Unknown/truncated floor evidence discards prior floor/sizes;
leaving a house discards context. There are no assumed size/model defaults.
A synthetic extension claiming verification without required fields throws;
those incomplete forms cannot be emitted by the existing wire decoder.

`WorldObstacleScope` ports the decision logic of `obstacle_scope.house_scene`
and `affects_navigation`, replacing the runtime lookup with explicit immutable
`WorldSceneCatalog` input. Without a supplied current catalog, ordinary-looking
IDs remain unknown and house-scoped geometry changes conservatively invalidate.
Known house templates/ranges always classify as houses. Known catalog stages
and verified instance aliases classify as ordinary; aliases only apply within
61501..62000. Unverified/absent aliases remain unknown.

The caller is responsible for current-version catalog provenance and successful
reviewed binary-order alias validation. This slice does **not** load or activate
a runtime, validate alias generation, resolve a house model, enable indoor
navigation, authorize movement, or wire reducers into a live session. Typed
scene IDs exclude Python's coercible strings/floats/bools. Malformed arbitrary
Python dictionaries are not an additional supported input protocol.

## Offline evidence

Regenerate the checked-in synthetic fixtures using retained Python:

```sh
python dotnet/Lala.Core.Tests/World/WorldEventGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~WorldEvent
```

The 371 focused tests comprise 68 differential sequences with 934 checkpoints,
288 obstacle-scope cases, and 15 contract tests. The sequences use the retained
`State`, real `apply_world_event`, helper methods, and wire decoder. Scope tests
inject a synthetic current-runtime lookup and alias-verification outcome only;
the Python scope decision itself is executed unchanged. No runtime is activated
and no official catalog, account, database, or server is used.

Coverage includes movement authority/target precedence, all relevant waiting
statuses and identity combinations, signed-role boundaries, scene/cache resets,
repeated leaves, cache refresh and eviction order, protected own slot, clear
counts, house range boundaries and floor-size accumulation/invalidation,
unknown/known/alias catalog scope, stale reason rollover, unbounded counters,
and deterministic mixed sequences. Every published checkpoint is retained and
rechecked after later updates. Contract tests also exercise 100,000 remote
updates, nested collection immutability, caller-owned counters, typed dispatch,
null inputs, missing verified-extension fields, and culture-independent IDs.

These tests establish only the listed shared-core offline behaviors. Full State
integration, runtime resource validation, route execution, live server parity,
desktop UX, and Android/device acceptance remain separate migration work.

Generated sequence JSON is stored as deterministic gzip/base64 text and decoded
only by the test fixture helper. All Python sequence and scope checkpoints remain
present. Re-run the generator to reproduce the compressed fixture.
