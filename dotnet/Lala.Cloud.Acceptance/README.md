# Bounded held-connection acceptance consumer

This executable references **only Lala.Core**, has no friend-assembly access, and uses
only Core's public APIs. It exercises explicit login plus held receive without
resource bootstrap, catalog downloads, UI, game commands, retry, or profile discovery.
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
