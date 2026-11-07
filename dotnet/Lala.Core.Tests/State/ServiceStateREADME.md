# Bounded offline service-state composition

`Lala.Core/State/ServiceStateCoordinator.cs` composes existing receive reducers with
`LocalStateCoordinator`. It is **not** a full `wlre.core.state.State` replacement,
connection/session adapter, service scheduler, or automatic game client.
`ServiceStateSnapshot.IsCompleteState` is always false.

## Source order and shared evidence

The complete order from `State.apply` is exposed by `ObserverOrder`, including bounded receive stages:

1. `apply_daily_tasks`: composed, including role-list and world-player resets.
2. `apply_cube`: composed, with explicit observation time and pre-local player.
3. `apply_recovery`: composed, receive balances only.
4. `apply_guild`: composed, receive roster and pre-local self-leave matching only.
5. `apply_activity`: composed through the existing `ActivityLocks` reducer.
6. `apply_crafting`: composed, receive crafting/furniture with explicit role/time.
7. `apply_storage`: composed, including its separate observed server-stackability map.
8. `apply_live`: composed receive slices: bag, companions, player/battle knowledge and current equipment. Command/learned-skill helpers remain outside this stage.
9. `apply_points_event`: composed, using updated player knowledge stats before local dispatch. Only already-imported pending allocations can change.
10. `apply_party`: composed, receive membership/requests with pre-local role; expiry is not scheduled.
11. `apply_expedition`: composed, receive state and explicit deadlines only.
12. `apply_instances`: composed, receive observers with pre-local role and explicit non-authorizing catalog map declarations.
13. `dispatch_local`: composed through the existing `LocalStateCoordinator`.
14. `apply_tent`: composed after local dispatch, using post-local role/scene.
15. `observe_shop_evidence`: composed with the current bag, post-local gold and updated count. No order descriptor or settlement is created.
16. `observe_efficiency`: composed through the immutable reducer, using complete updated player/companion knowledge and post-local role/name.
17. `apply_actions`: composed with updated guild and post-local player/gold. The separate `tick` prefix does not run here.
18. `apply_ark`: composed with updated daily generation and post-local role, explicit runtime observations, and unexecuted identity-bound memory intents.

All eighteen source observer positions now have bounded receive composition.
This is not full-State parity: action helpers, scheduler-only observation prefixes,
persistence, catalog activation and other retained State APIs remain separate.
Efficiency uses immutable reduction, never a mutable tracker or fabricated empty
knowledge. See [post-local integration evidence](ServicePostLocalREADME.md).

The observation's new packet count is calculated before the supported observers.
All pre-local observers share the old player and phase. Local dispatch advances its
private count once and supplies the post-local player and phase. The immutable
`Observation.BeforeLocal` and `AfterLocal` evidence record this distinction, with
the same new packet count on both sides. Decode uses the coordinator's current
player, never an account ID, external bag, or caller-guessed role.

## Ownership, atomicity and inputs

- Construct/apply/read the coordinator on its owner thread. Capture snapshots there
  and pass the immutable snapshots, not the coordinator, to other threads.
- Supply `ServiceObservationContext` for each observation, binding explicit inputs
  to the **exact current snapshot**. Reusing a stale or unrelated basis fails before
  decoding or counting; equal role/count values do not bypass the check.
- Time must be finite and explicit. Recorded clock regression is accepted as in the
  source. No clock, network, filesystem, callbacks or resource loading is invoked.
- World scene catalog is per observation. Omitted means unknown, not reuse of an old
  catalog. Missing daily, schedule, item-stack, NPC-skill and combat-knowledge inputs remain unknown. `ResourceHeld`
  defaults to true. These inputs are caller evidence, not resource verification,
  admission, catalog activation, or action authorization.
- Daily catalog evidence is retained for inspection only. Bag evidence comes from the owned snapshot, never an external contradictory RewardBag. Receive observers do
  not call `Tick` or `Request`, create candidates, settle pending rewards, expire
  requests, reserve items, or send packets, even with elapsed deadlines, eligible
  rewards, a reliable changed bag, or an explicitly false resource hold.
- Every successful decoded observation counts once, including ignored, unsupported
  and unimplemented events. Duplicate/late observations are not deduplicated.
- All reducers stage privately; the composite snapshot/count is assigned only after
  success. Decode errors, stale/invalid context and typed reduction failures leave
  the exact previous snapshot intact. **This transactional typed-error behavior is
  stronger than Python and the standalone local coordinator**, which may increment
  or partially mutate before a hand-built event fails. Wire-error parity is unchanged.
- No implicit role/session invalidation is invented. Role selection resets daily
  and cube state but retains old player, guild, activities, storage and expedition
  as the source does. Every world-player observation clears activities; daily/cube
  receipts reset only on a changed known role. Stale guild/expedition data is not
  proof of current membership or permission to act.

## Cross-domain limitations

The bag and storage share exactly one observed server-stackability map. Imports
reject contradictory maps. Companion S8 buffers retain source insertion order and
must agree with local follow:* attributes; deletion/reassignment clears both views
before local dispatch records a new attribute. Snapshot imports reject inconsistent
projections rather than guessing. `BeforeObserversBag`, `BeforeLiveBag` (after
storage), and `AfterLiveBag` record three distinct immutable stages.

Player/battle knowledge and equipment flow through apply_live, and the post-local
observers consume these exact results. Composing their bounded receive subsets
does not complete full-State parity. Raw S8 values and injected NPC mappings
are not verified catalogs or action authority. The common dispatcher requires
explicit CraftingScheduleContext for layout-dependent schedule records.
All service actions, scheduling, lifecycle/disconnect policy, persistence, live
catalog activation, transport, UI, Android wiring, device and official-server
acceptance remain outside this increment.

## Verification

`ServiceStateGenerateVectors.py` runs the **real `State.apply`**, including all 18
source observers. Transparent wrappers capture their actual order and pre/post local
player, phase and count; observers are never replaced with no-ops. Only monotonic
clock and current runtime inputs are explicitly supplied. Data and catalogs are
synthetic. Source hashes pin the entry point, dispatch and observer implementations.

The retained corpus contains 14 scenarios, 698 checkpoints and 36 decoded event
kinds. It compares complete supported local/daily/cube/recovery/guild/activity/storage/
expedition projections and every historical snapshot. Cases cover large counters,
role changes, repeated/late observations, reset barriers, guild self-leave identity,
catalog changes, clock regression, malformed packet rejection and interleaved domains.
The supported subset is intentionally narrower than all observer interactions.

Sixteen additional contract cases cover owner-thread checks, stale/foreign contexts,
immutable history, atomic errors, invalid clocks, unknown metadata, explicit gaps,
resource holds and the absence of automatic settlement/requests. Two oracle contract
tests check full source order and source hashes. Regeneration is deterministic.

```sh
python dotnet/Lala.Core.Tests/State/ServiceStateGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
```

Verification on this worktree: Core Release 15,390 passed; Android lifecycle 59
passed; Desktop Release build had zero warnings/errors and its offline self-test
passed 9 checks. Python discovery ran 2,273 tests, OK with 216 skipped, using the
existing UnityPy 1.25.4 dependency directory. The default Python without that
directory first failed one missing-UnityPy import; no dependency was installed.

No live login, send, purchase, formal-server probe, runtime download or credentials
are involved. Passing offline tests does not constitute official-resource/platform/
server acceptance or completion of the Python module migration.

## Mixed inventory integration verification

`ServiceInventoryGenerateVectors.py` adds 13 real State.apply scenarios, 524
checkpoints and 30 event kinds. It compares all previously covered projections plus
bag/reservations, crafting/furniture and companion buffers, with historical
immutability, stage-specific bag evidence, explicit layout selection, context
changes, malformed packets and atomic rollback. Source hashes in both oracles
normalize CRLF byte pairs only; all other source bytes remain significant.

Party, instance and tent composition adds 22 real State.apply scenarios, 679
checkpoints and 50 event kinds. It preserves the old-role/new-role boundary and
uses empty instance map declarations by default. No expiry, timer, request or
send is scheduled. See `ServiceSocialInstanceREADME.md` for the exact contract.

## Combat knowledge and allocation integration

See [mixed knowledge/allocation evidence](ServiceKnowledgeAllocationREADME.md).
The composite owns `PlayerKnowledge` and `AttributeAllocation`. Player equipment
resolution runs before the inventory early-return equivalent. Each existing bag
and companion slice runs once. All returned companion and battle projections
flow forward, including S11 equipment overlays. Local dispatch consumes that
returned battle state, preserving equipment through later local events.

`ServiceObservationInputs.KnowledgeCatalog` supplies per-observation, explicitly
unverified skill-key and item-fit mappings. Omitted means unknown, never reuse.
`Observation.AfterLivePlayerKnowledge` and `AllocationContext` retain the exact
knowledge projection and widened `BigInteger` stats used by allocation before
local S8 writes. Raw session attributes are never allocation evidence.

## Post-local observer integration

See [mixed post-local evidence](ServicePostLocalREADME.md) for source-order,
identity, persistence-intent and rollback boundaries. The composite now owns
`ShopEvidence`, `Efficiency`, `GuildActions`, and `Ark`. `Observation` retains the
exact shop context, projected efficiency knowledge, guild-action context, consumed
Ark runtime context and at most one unexecuted Ark memory intent for that packet.
Later publications never silently carry or execute a prior packet's intent.
