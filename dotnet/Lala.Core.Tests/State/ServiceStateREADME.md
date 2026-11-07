# Bounded offline service-state composition

`Lala.Core/State/ServiceStateCoordinator.cs` composes existing receive reducers with
`LocalStateCoordinator`. It is **not** a full `wlre.core.state.State` replacement,
connection/session adapter, service scheduler, or automatic game client.
`ServiceStateSnapshot.IsCompleteState` is always false.

## Source order and shared evidence

The complete order from `State.apply` is exposed by `ObserverOrder`, including gaps:

1. `apply_daily_tasks`: composed, including role-list and world-player resets.
2. `apply_cube`: composed, with explicit observation time and pre-local player.
3. `apply_recovery`: composed, receive balances only.
4. `apply_guild`: composed, receive roster and pre-local self-leave matching only.
5. `apply_activity`: composed through the existing `ActivityLocks` reducer.
6. `apply_crafting`: **not composed**; crafting/furniture receive state remains absent.
7. `apply_storage`: composed, including its separate observed server-stackability map.
8. `apply_live`: **not composed**; bags, knowledge, skills, companions and equipment absent.
9. `apply_points_event`: **not composed**; attribute allocation absent.
10. `apply_party`: **not composed**; party membership/requests absent.
11. `apply_expedition`: composed, receive state and explicit deadlines only.
12. `apply_instances`: **not composed**; instance receive/service state absent.
13. `dispatch_local`: composed through the existing `LocalStateCoordinator`.
14. `apply_tent`: **not composed**.
15. `observe_shop_evidence`: **not composed**.
16. `observe_efficiency`: **not composed**.
17. `apply_actions`: **not composed**; guild sign-in/donation state absent.
18. `apply_ark`: **not composed**.

Efficiency's existing mutable tracker needs post-live knowledge and a transactional
snapshot import/restore contract before it can join this coordinator. It is not run
with fabricated empty knowledge. Independent crafting/live receive work is not
integrated by this increment.

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
  catalog. Missing daily catalog and bag evidence remain unknown. `ResourceHeld`
  defaults to true. These inputs are caller evidence, not resource verification,
  admission, catalog activation, or action authorization.
- Daily catalog/bag evidence is retained for inspection only. Receive observers do
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

Omitted observers can modify fields also present in local projections. In particular,
`apply_live` clears buffered companion attributes on deletion/replacement and updates
battle equipment. Those effects are **not** supplied here. The local projection is
therefore local-dispatch parity, not full-State parity for such events. Storage's
`server_stackable` observations remain a separate receive map, not a reconstructed
bag or verified item catalog. Raw S8 values are not complete player/companion knowledge.
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
