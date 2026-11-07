# Mixed combat knowledge and allocation receive composition

`ServiceStateCoordinator` composes the remaining `CombatKnowledgeReceiveReducer`
and the receive-only `AttributeAllocationReducer` in the retained `State.apply`
order. This is offline Core state, not a session adapter or complete State.

## Composition and ownership

- `PlayerKnowledge` and `AttributeAllocation` are owned immutable snapshots.
  Allocation starts only from explicitly imported pending evidence; no receive
  observation creates a request, spends points, or schedules expiry.
- The knowledge reducer resolves pending player equipment before bag writes,
  even for unrelated or inventory-handled events. Bag and companion receive
  slices each run once. All returned player, companion and battle snapshots
  flow forward. Local battle dispatch consumes the returned battle projection,
  retaining S11 appearance overlays while preserving original layouts.
- Allocation receives updated `PlayerKnowledge.Stats`, exactly widened from
  `long` to `BigInteger`. It never reads raw `SessionEventSnapshot.Attributes`.
  The same packet can update knowledge and finish an acknowledged allocation
  before local dispatch writes its S8 buffer. Battle/S5-star knowledge updates
  alone are not qualifying allocation receipts.
- Local companion buffer reconciliation stays in place: deletion/reassignment
  clears both views, and local S8 is observed once. Replacing an S15 profile
  resets equipment overlays while same-identity buffered attributes replay.
- Party/instances retain pre-local identity; tent retains post-local identity
  and scene. Every successfully decoded event counts once. Source role changes
  do not invent knowledge/allocation resets or authorize any operation.
- `KnowledgeCatalog` is explicit, immutable, per-observation skill-key/item-fit
  evidence, separate from NPC skill and stack maps. Missing mappings stay
  unknown. Nothing verifies, activates or caches a runtime catalog.
- `Observation.AfterLivePlayerKnowledge` and `AllocationContext` expose the
  exact immutable inputs used before local dispatch. All reducers stage
  privately. Decode, context or typed-reducer failure publishes no state and
  no packet count, a stronger typed-error boundary than mutable Python State.

## Differential evidence

`ServiceKnowledgeAllocationGenerateVectors.py` executes the real `State.apply`
with transparent wrappers around all 18 observers. No observer is replaced by
no-op code. It captures actual allocation stats before local S8 dispatch and
checks the full source order, pre/post-local identity and count, and bag stages.
Only synthetic catalog rows, explicit clock values and offline runtime input
projections are supplied.

The corpus contains **26 scenarios, 1,064 checkpoints and 34 decoded event
kinds**. Each checkpoint and historical snapshot compares every previously
composed domain (session, world, battle, daily, cube, recovery, guild, activity,
storage, expedition, bag/reservations, companion buffers, crafting/furniture,
party, instances and tent), plus player knowledge, current companion/battle
gear and allocation state. Cases include ACK/value order, S5 replacements,
long/unsigned extremes, missing/case-sensitive stats, unknown and changed
roles, pre-local battle occupant matching, S11 persistence, S15 identity reuse,
late/partial/omitted catalogs, inventory early returns, both 256-update queue
boundaries, malformed packets, large counts and mixed-domain arrivals.

Contract cases separately test contradictory raw attributes, exact numeric
widening, all local dispatch partitions, single companion insertion, single
bag revision, immutable imports, catalog non-retention, and rollback after
knowledge staging or typed battle failure.

```sh
PYTHONPATH=/tmp/daily-assistant-deps python3 dotnet/Lala.Core.Tests/State/ServiceKnowledgeAllocationGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~ServiceKnowledgeAllocation
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
```

Fixtures use the shared TestSupport deterministic gzip byte helper. Large byte
arrays are split into generated methods/files, never Base64 strings or fixture
payloads in the CLR user-string heap. Every file is below 500 KB. Source hashes
normalize only single-pass byte CRLF-to-LF pairs, preserving every other byte.

## Remaining boundaries

`IsCompleteState` stays false. `observe_shop_evidence`, `observe_efficiency`,
`apply_actions` and `apply_ark` remain uncomposed. Receive composition does not
port combat command selection, learned-skill remapping, spending/begin/expiry,
requests, ticks, timers, transport, live catalogs or resource activation. No
AccountSession, connection/lifecycle API, Android or UI implementation changes.
Passing these offline checks is not complete Python module migration or
resource/device/official-server acceptance.

## Verification on this increment

On base `8f41e26` plus this integration: focused knowledge/allocation tests
40 passed; full Core Release 17,492 passed; unchanged Android lifecycle 59
passed. Desktop Release built with zero warnings/errors and its offline
inspector passed 9 checks. Retained Python discovery ran 2,273 tests, OK with
216 skips, using the existing UnityPy dependency directory; the focused
attribute/routing suites passed 14 tests.

Successive fixture regenerations matched all nine generated files exactly.
Independent review also reran the real Python oracle in memory and reproduced
all nine files byte-for-byte. Largest generated file: 442,090 bytes.
`git diff --check` passed. No native Android build/device, UI, login, live send,
download or official-server acceptance was attempted.
