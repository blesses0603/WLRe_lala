# Bounded held-account acceptance consumer

This executable references **only Lala.Core**, has no friend-assembly access, and uses
only Core's public APIs. Its default connection-only mode exercises explicit login
plus held receive without resource bootstrap or catalog downloads. An explicit
host-only factory also composes `AccountRuntime` connection and resource ownership.
Neither mode adds UI, game commands, retry, or profile discovery.
It is not official-server or live-account validation.

## Run synthetic checks

From the repository root with the .NET 10 SDK:

```sh
dotnet run --project dotnet/Lala.Cloud.Acceptance -c Release -- --self-test
```

No arguments, `--help`, or `-h` prints prerequisites without opening sockets. All
other arguments fail without being echoed. `--self-test` binds synthetic peers only
to IPv4 loopback with ephemeral ports and uses fake transient credentials. It does
not load configuration or credentials from arguments, environment variables, files,
or stdin. There is no hidden live mode or production/default target.

The self-tests cover complete login followed by a deliberately late heartbeat,
both world/initial-data arrival orders, completed-but-silent receive, early EOF,
post-login protocol failure, rejected/incomplete login, overall timeout, cancellation,
pre-cancellation, noncooperative credential return after an observed stop barrier,
fresh credentials and a single attempt per new runner, source ownership, redaction,
bounded options, and cleanup-failure **classification**. Real transport cleanup
failure is not injectable through the concrete public Core API; that last check is
a pure classification test, not an end-to-end failure injection.

Seven additional integrated-mode checks exercise pre-cancellation, credential decline,
provider exception redaction, rejected/incomplete verification login, noncooperative
credentials after deadline, and absolute-root validation. They use the real public
`AccountRuntime.Create` factory and assert no resource history, no readiness, no
formal connection and no data-root creation. They deliberately cannot finish login:
finishing even synthetic login would admit the production official HTTP source.
No public resource-source injection or fake authority is used.

The peers assert exact allowed login/selection/map/appear/heartbeat frame headers and
reject all extra client traffic before EOF. The late heartbeat is sent only after
the runner publishes its baseline, and its exact reply is checked at the peer.
Synthetic received frames and caller-owned credential buffers are explicitly cleared.
No result logs include exceptions, account details, destinations, state or packets.

## Future authorized secure host

The runnable CLI has no secure credential adapter. A host may reference this assembly
and construct `CloudAcceptanceRunner` with an explicitly selected
`AccountConnectionProfile`, a caller-owned `IAccountCredentialSource`, and optional
`AcceptanceOptions`. Construction is inert. Call `RunAsync(cancellationToken)` and
await the result. Repeated calls on the same runner return the same task; its first
token owns cancellation. A new runner owns a fresh session and permits one attempt,
without reconnect or automatic credential reacquisition.

The host must obtain authorization for the intended account and endpoints and supply
credentials through its approved secure adapter. It must clear its own original
buffers and honor source cancellation. The returned `AccountLoginCredentials` object
transfers to Core and is disposed there; the source itself remains caller-owned.
Raw TCP/XOR is **not encryption**. A trusted network arrangement is a separate
prerequisite. No example endpoint, account, or reusable secret is shipped here.

`Snapshot` and the final result retain only enums and counts. They are safe to format
without printing Core receive state or credential/provider exception messages.
Live `Publication.State` is inspected only to establish the committed handshake
baseline and is never retained in the public result.

## Evidence and bounds

- Protocol completion comes from public `ReceivingHeld` or completed attempt history.
  It never grants resource/gameplay authority.
- The first held publication with both world player and initial-data completion
  establishes the revision baseline. This prevents a pre-commit phase transition
  from counting its final login commit as subsequent receive progress.
- A later revision in the same attempt is receive progress. It is not proof of a
  heartbeat, full state coverage, lossless observation, or a specific packet type.
  Polling can miss an extremely short-lived publication; missing evidence is never
  promoted to success.
- The full observation window ends with a stop request. The result distinguishes
  protocol-complete with/without subsequent progress, incomplete/rejected login,
  credential/connection failures, interrupted observation, cancellation, deadline,
  and cleanup failure. Native failure or early EOF cannot become success merely
  because protocol login or a later revision was already observed.
- The independent overall timer also applies while acquiring credentials and after
  successful login. Cancellation and timer expiry call `Stop`, immediately revoking
  further admission. A late source result is cleared without dialing or sending.
- **These are stop-request bounds, not hard completion deadlines.** The runner awaits
  both Core `RunAsync` and `DisposeAsync`, joining admitted callbacks and cleanup.
  A noncooperative callback can delay completion indefinitely. Nothing is detached
  to manufacture a timeout result. Cleanup failure overrides other classifications.

The default observation window is 5 seconds, the overall stop budget 45 seconds,
and the polling interval 20 milliseconds. Options have finite upper bounds. Tests
use short windows and a separate 15-second diagnostic guard per scenario.

## Explicit integrated host mode

A separately authorized secure host may call
`CloudAcceptanceRunner.CreateWithResources(profile, source, absoluteDataRoot, options)`.
The absolute root is validated before any source invocation. Construction remains
inert, but is **not authorization**. After login, `RunAsync` may download official
HTTPS resources and create or update the fixed SQLite inventory at
`official_sync/derived_catalogs/resource_inventory.sqlite3` beneath that root.
The host must authorize those network and database operations as well as the
account/connection. The executable offers no integrated live CLI and no default root.

Both modes use the same single-attempt, observation, stop and cleanup loop. Overall
and observation bounds still request stop, and admitted resource work is joined.
Cleanup failure from either connection or resource ownership overrides the outcome.
The observation window is not extended to wait for resources: a slow preparation
may be cancelled when the connection observation finishes.
The observed operation includes resource draining. If the connection ends before a
baseline is sampled but admitted resource cleanup is still pending, the overall
stop budget may expire before aggregate completion is observed. That result remains
conservative deadline evidence, not proof that the connection stayed open.

`Outcome`, `Login` and `Receive` describe **connection observation only**, not overall
account/resource acceptance. `Resources` is separate sanitized evidence:

- `Disabled` identifies the original connection-only mode.
- `NotObserved` means current resource readiness was never observed. It does not
  assert that no preparation started; only completed preparations enter history.
- `CurrentReadinessObserved` is historical: current resources were observed at
  least once. Cleanup revokes them, so the final result never claims resources
  remain current or grants command authority.
- Preparation count and last status/storage/readback/source-recheck facts describe
  completed preparation history, including work drained during shutdown. A database
  commit is not rolled back merely because the run later stops or fails.

Polling can miss short-lived readiness. Protocol completion does not imply resource
readiness; successful preparation history does not imply currently usable catalogs.
No raw paths, sources, versions, catalog contents or exception details enter evidence.

**Public consumer resource success is untested offline.** Successful connection plus
resource joins, revocation and inventory operations are tested separately by Core's
internal `AccountRuntimeIntegrationTests.cs` fixture suite. Those tests do not prove
production HTTP success or official-account acceptance. A public-only synthetic
successful resource run is intentionally unavailable without real official fetching.
