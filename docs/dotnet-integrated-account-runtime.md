# Integrated account runtime

`AccountRuntime.Create` joins the public connection and resource runtimes for one
account generation. It is inert until `RunAsync`, which can send login credentials
to the explicit TCP profile, fetch official HTTPS resources, and write the fixed
SQLite resource inventory and verified version-keyed bundle cache during bootstrap.
Callers must authorize those effects before starting.
Neither successful login nor valid catalogs enable game commands.

## Lifetime and ordering

- Connection login runs first. No resource operation starts before the controller
  reaches `ReceivingHeld` for a current attempt.
- The first receiving attempt gets one bootstrap operation. Later receiving
  attempts use read-only refresh, never an automatic replay of the database write.
  This remains conservative even when the first bootstrap failed or was cancelled.
  Bootstrap populates the [bundle cache](dotnet-resource-bundle-cache.md) after independent
  inventory readback and before final source reobservation. Later refreshes reuse verified
  bundles, but missing/corrupt cache downloads are not saved by refresh.
- Lifecycle changes use asynchronous identity-based signals rather than polling.
  Stop/reconnect revokes catalog selection immediately at the read boundary and
  requests cancellation of resource preparation. A pending, noncooperative resource
  callback must finish before another preparation starts or disposal completes.
- Current catalogs are joined only to the exact session snapshot and receive
  attempt. A successful historical preparation is not current authority.
- Failure/uncertainty in resource preparation leaves the connection held. It does
  not trigger a database rewrite or a login retry. Inspect/recover the inventory
  explicitly before choosing any later write.
- `Stop` revokes publications synchronously. Run completion joins connection and
  resource cleanup. Dispose before Run performs no login or resource acquisition.
  Aggregate cancellation/disposal uses this same stop boundary, so the underlying
  connection reason is `Stopped`; it does not claim a protocol failure.
- Receive retirement publishes `Draining` before transport cleanup completes, so
  resources are revoked even when that cleanup is slow or noncooperative.

## Awaiting integrated status

`Snapshot` retains its exact object identity until the visible connection status,
current-resource selection, resource history, or aggregate completion changes.
`WaitForChangeAsync(snapshot, cancellationToken)` accepts the exact observed instance.
A stale, value-equal clone, or another runtime's snapshot returns the current state
immediately. A canceled token is checked even for stale or completed snapshots, and
canceling one wait does not stop the runtime or other observers.

The integrated wait covers connection lifecycle changes, resource readiness and
revocation without a connection change, historical preparation outcomes, and cleanup
completion. Account `Begin`, `Hold`, and `Disconnect` changes use internal identity
signals to invalidate a joined binding; no polling or extra received packet is needed.
Source signals and the integrated signal run continuations asynchronously, never user
callbacks under their lifetime locks. One owned notification pump retains at most one
wait per source and cancels and observes losing waits each cycle. Dispose drains this
pump together with connection/resource work. Construction and waiting before Run do
not start login, resource acquisition, or database writes.

Changes may coalesce, so this is a status notification API, not an event queue or
receive-packet stream. Receive commits alone do not change this status or release its
waiters. Use the separate publication API below to observe receive changes. Retained
snapshots and catalogs remain historical observations and never grant command authority.

`AccountRuntimeStatus.IsCompleted` means the entire run, including pending resource
history and owned cleanup, has finished. `Connection.Phase == Ended` can occur earlier
while a resource callback or cleanup is still draining. Continue waiting until
`IsCompleted` rather than looping on the connection's terminal phase. A wait on an
already completed integrated status returns immediately, including after disposal.
Completion does not mean cleanup succeeded: inspect the Run result's
`ResourcesReleased`, or await Dispose, which reports cleanup failure.

## Awaiting receive publications

`PublicationSnapshot` is a non-null `AccountRuntimePublicationSnapshot` containing
`Connection`, nullable `Publication`, and aggregate `IsCompleted`. It retains its exact
object identity until one of those visible components changes. `Connection.RuntimeId`
identifies the owning connection lifetime; its `Generation` and the receive `Attempt`
identify a replacement. A receive revision counts committed packets within one attempt,
not across reconnects. Lifecycle-only changes do not increment that revision.

`WaitForPublicationChangeAsync(snapshot, cancellationToken)` waits for receive commits,
receive lifecycle changes, catalog binding or revocation, connection changes, and final
aggregate completion. Pass the exact snapshot returned by this runtime. Stale snapshots,
value-equal clones, and snapshots from another runtime return its current snapshot
immediately. A canceled token takes precedence even on that fast path. Each waiter can
be canceled independently. An already completed snapshot returns immediately, so hosts
should exit their observation loop on `IsCompleted`:

```csharp
var snapshot = account.PublicationSnapshot;
while (true)
{
    RenderReadOnly(snapshot); // Host-selected UI/logging policy; do not dump raw state.
    if (snapshot.IsCompleted) break;
    snapshot = await account.WaitForPublicationChangeAsync(snapshot, cancellationToken);
}
```

The wrapper remains non-null before Run, between attempts, and after Stop even when
`Publication` is null. Thus connection creation/retirement and final cleanup cannot be
mistaken for an unchanged absent publication. Stop revokes the current publication at
the read boundary before returning; pending cleanup still keeps `IsCompleted` false.
Dispose-before-Run wakes observers without acquiring credentials or resources. Like the
status API, completion is not proof that cleanup succeeded.

`Publication` is also a stable wrapper until its receive or catalog reference changes.
The connection status and receive attempt are captured under the same ownership lock;
catalogs are joined only against the exact current account snapshot and that attempt.
Receive and resource production are independent: this is not a shared transaction or a
promise that the receive state's historical observations already used the newly bound
catalogs. They are used on subsequent commits. Revocation does not mutate retained
snapshots or replay old packets. A returned snapshot may already be historical when the
host consumes it and is never permission to act.

The existing owned notification pump also observes one rotating receive signal. It
subscribes before pulling the joined view, cancels and observes losing waits each cycle,
and is drained with the runtime. There are no per-host pumps, new user callbacks, polling,
or per-packet notification queues. Signals run continuations asynchronously. Changes can
coalesce and intermediate states may not be observed; this is not a lossless event log.
Resource history changes without a visible catalog change still belong to the separate
status API. Constructing the runtime, reading snapshots, or awaiting a change does not
start network or resource work.

## Receive observations

A current resource binding supplies decoded stage IDs, reviewed item stackability and
reviewed equipment-fit rules and reviewed NPC skill-slot IDs to the actual receive observer. Item fits and NPC slot identities are independent
of optional skill availability and use the receive reducers without action authority. Missing aliases, skill maps and optional tables
stay unknown. Older receive snapshots can retain historical observations; they never
permit actions. Resource hold remains true at every receive commit.

The account runtime explicitly sets `ReconcileNpcSkills` on each observation,
including observations without a current resource binding. This resolves retained
S15 slots when reviewed NPC metadata arrives later, and removes only
metadata-derived skills when the mapping changes or becomes unknown. S8 skill
overrides/removals, occupant identity, raw slots, statistics, equipment and historical
immutable snapshots are preserved. The projection does not replay the local S8
buffer, whose foreign-human writes are replayed only by a fresh S15.

Standalone reducer and service inputs default this option to false, preserving
Python's stored `set_companion` behavior and the retained receive parity fixtures:
unrelated observations do not rebuild stored skills. Stored duplicate NPC slots
keep the first insertion position and last positive value; the separate pure
`Learned` projection continues to use the first positive duplicate from the current
explicit catalog. Neither projection enables commands.

`Snapshot` exposes bounded sanitized lifecycle/resource history. `Publication` is a
read-only point-in-time receive/catalog pair and becomes null after stop. Catalogs
and receive state must not be logged wholesale. The runtime exposes no command-send
operation and does not call `ConfirmResources`.

### Crafting schedule identities

A current binding also projects the complete parsed `SmithData_C` recipe catalog into
`CraftingSchedules`. The identity pair is `RecipeId`/`ItemId`; the product-only lookup
is deliberately not used because different recipes can produce the same item. Timed
and read-only recipe rows remain part of this receive identity map. Parsed legacy rows
explicitly select item-ID schedules; recipe-keyed rows use the existing strict identity
validation. No wire-packet length selects the layout, and unknown recipe IDs are rejected
without a partial receive commit or a fallback to item IDs.

Missing, empty, or revoked catalogs leave schedule context unknown. S64-1 and S64-16
packets received before the binding or after revocation remain unsupported. They are not
buffered or replayed when resources arrive; a later binding alone does not establish a
received schedule snapshot. The integrated runtime explicitly enables
`TrackUnsupportedCraftingSchedules` on both bound and unbound observations. A skipped
S64-1/16 retains the historical queue but marks it uncertain/not ready and stops its
running clock. S1-11, a later catalog, and S64-16 deltas cannot repair that gap; a fresh
decoded S64-1 is needed. The independent furniture login barrier remains unchanged.
Standalone observations default the policy to false, preserving Python parity.
Previously published snapshots remain immutable historical observations, never command
permission. This adds no resource download, database write, UI, command, or automatic
crafting behavior.

## Validation limits

Integration tests combine synthetic TCP peers, fixture bundles and actual temporary
SQLite writes/readback. White-box binding tests explicitly simulate only the private
owner trust bit and do not prove official provenance or live acceptance. The ordinary
fixture source continues to fail resource admission. No Desktop/Android host UI is
changed, and no official server or real credential is used by these tests.

Crafting-context verification on the restored cloud .NET 10.0.403 SDK passed 2,241
focused cases and all 43,223 Core tests, with no skips. This includes 22 new projection,
framed receive, and service-policy cases, plus the existing AccountRuntime binding tests
extended to decode S64 and withdraw context. The first compile exposed two test-fixture
constructor calls missing the nullable reviewed-details argument; those were corrected
to `null`, without changing production behavior. Independent review found no blocker.
Platform host builds and CI remain separate checks; no live server was used.

Integrated-status notification validation adds 11 cases covering exact snapshot
identity, independent/racing cancellation, asynchronous fanout, resource-only readiness
and history, account replacement/hold/disconnect, and late history/cleanup completion.
The final cloud Release Core suite passed all 43,237 tests with no skips. The external
public-contract smoke check also passed without network access or resource writes.
Independent review found no blocker; these remain offline checks, not host UI or live
server acceptance.

Receive-publication notifications add 12 focused cases: real framed loopback commits
without waking status-only waiters, exact/cloned/foreign snapshot identity, cancellation
and asynchronous fanout, catalog-only binding/revocation, Stop/Hold/Begin/Disconnect,
reconnect generation/attempt joins, and delayed or failed aggregate cleanup. The final
cloud .NET 10 Release suite passed all **43,384 Core tests with no skips**, and the
external public-contract check passed without network access or resource writes. These
checks use synthetic peers and owned fixtures; they do not prove production resource
provenance, host UI behavior, or official-server acceptance.
