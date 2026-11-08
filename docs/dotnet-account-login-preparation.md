# One-attempt account login preparation

`AccountLoginPreparation` is an optional, inert Core composition for a future host.
It privately owns the exact immutable `AccountConnectionProfile`, a current preparing
`AccountSession` snapshot, an opaque selected-identity marker, one input acquisition,
and one `AccountConnectionRuntime` attempt. It exports the disclosure, read-only
status/publication, and lifecycle operations. It does not export a reusable credential
source or accept a second profile at run time. No Desktop/Android input host is installed.

## Host responsibilities and permission boundary

Read `Disclosure` before calling `RunAsync`. It identifies both IP/port recipients,
role, platform, language, XOR bytes, generation, opaque selected identity, fixed login
purpose, maximum validity and attempt count. Endpoint getters return defensive copies.
The host must independently authenticate the user's action-time permission for these
exact facts, including the raw-TCP risk, before invoking `RunAsync`. Core supplies no
approval enum, authenticated click, trusted-input claim, identity proof or saved consent.
Calling a method is not evidence that the host obtained permission. An opaque GUID is
only a host selection marker; the host must bind that marker to the actual account input.

`IAccountLoginInput` receives that same disclosure object and must return fresh,
exclusively owned `AccountLoginCredentials` or null to decline. It must clear its own
original input, avoid logging/secrets in errors, and honor cancellation. It remains
caller-owned and is never disposed by Core. A malicious or aliased source cannot be made
safe by this cooperative interface. The original `IAccountCredentialSource`/runtime API
remains available for existing callers; it does not gain these preparation guarantees.

Fixed XOR is reversible obfuscation, not TLS or encryption. Both recipients and network
observers may recover the account/password. This increment supplies no actual input UI,
secure OS handoff, safe network, real credentials, default official endpoint, deployment,
or official-server validation. No captured or real credentials are used in its tests.

## Binding, expiry and revocation

- Construction performs no acquisition or network request. The preparation accepts only
  a current `Preparing` generation and `MaximumAttempts == 1`. Repeated/concurrent runs
  return one task; neither decline nor failure nor cancellation can reacquire or retry.
- A monotonic lifetime of at most 60 seconds begins at disclosure construction, not at
  input completion. It is checked before and after acquisition, before packet creation,
  and at each actual credential-write admission, including formal login after verification.
  Timers are rechecked/rearmed if they wake early. Pending input receives cancellation
  after expiry. At exactly the lifetime limit no new credential leg is admitted.
- Admission checks reference-identical session snapshots. Only this preparation's own
  transition into Held receive attachment advances its expected snapshot. Begin,
  Disconnect, ConfirmResources, and even another Hold at the same generation invalidate
  it. Session changes and write admission share session-first lock ordering. An async
  watcher cancels pending input; synchronous snapshot checks prevent a send while that
  watcher is waiting to run.
- Host-only selection or profile changes must call `Stop`/`DisposeAsync` on the old
  preparation and create a new one with a fresh disclosure and independently obtained
  permission. Core cannot observe an unrelated host field changing by itself.
- Both login legs must match their exact pinned endpoint and expected leg order.
  The admission check wraps actual TCP write admission, not merely credential acquisition
  or packet construction. The lock order is session, preparation admission, login
  transport, then TCP. No host input or observer executes under these locks.
- Stop/disposal revoke admission synchronously. Cancellation is checked at admission.
  A write admitted before retirement can already have reached the socket; it cannot be
  undone, and bytes may arrive after cancellation. This is not atomic network delivery
  or proof of remote receipt. Partial/uncertain writes are terminal and never replayed.
- Once the formal credential write is admitted, this preparation's expiry is spent; it
  does not disconnect a healthy receive-only session a minute later. Subsequent explicit
  cancellation, Stop, disposal and session changes still retire the connection. Existing
  login/read/write timeout policies remain in force.

## Ownership and truthful completion

The input source is detached after acquisition. Returned credential buffers and owned
packet/encoded-byte copies are cleared by the existing runtime on success/failure.
Late credentials returned after cancellation or context replacement are disposed without
connecting. Exceptions are reduced to existing sanitized connection outcomes.

`RunAsync` and `DisposeAsync` remain pending until admitted input callbacks return and
owned cleanup actually completes. A callback that never finishes therefore leaves
cleanup pending indefinitely, even after status reports Stopping. Synchronous blocking
input callbacks and blocking disposal also remain unbounded. Cancellation is not successful
cleanup; process termination before return can prevent cleanup. Buffer clearing cannot
remove caller copies, managed-runtime copies, OS input buffers, swap or crash dumps.

Successful protocol login remains `ReceivingHeld`; resource holds and the absence of
a game-command send API are unchanged. This preparation does not itself join resource
bootstrap or make the existing integrated `AccountRuntime` a permission boundary.

## Synthetic verification

Loopback tests observe exact synthetic credential packets at the two pinned recipients,
exercise decline and sanitized input failure, pre-cancel/dispose, generation replacement,
same-generation Hold, disconnect, pending noncooperative input/late cleanup, one-attempt
reuse prevention, and 59/60/61-second monotonic boundaries. Additional internal synthetic
providers invalidate expiry/context/cancellation **after packet construction**, proving
that both actual credential writes are blocked at transport admission. A completed formal
login continues receiving/answering the existing heartbeat after preparation expiry.

`Lala.Core.PublicContract.Check` consumes the public preparation with a pre-cancelled token
without friend-assembly access, input acquisition or network requests. These checks are
not proof of a secure host, authenticated human approval, official-server compatibility,
or production security acceptance.

## Opt-in acceptance consumer

`Lala.Cloud.Acceptance` now offers `CloudAcceptanceRunner.CreatePrepared` as an
inert public-API consumer. It freezes its private session/generation and preparation
at construction and exposes the exact `Disclosure` before Run. It does not acquire
input, authenticate permission, export a reusable source, accept a replacement profile,
or implicitly enable resource bootstrap. The original constructor and resource factory
remain legacy raw-source routes without these guarantees. See the
[acceptance host contract](../dotnet/Lala.Cloud.Acceptance/README.md#opt-in-prepared-login-host)
for lifecycle and synthetic coverage.


A separate acceptance `--terminal-self-test` now exercises intercepted local terminal
input through the prepared runner with only the fixed fake pair and embedded loopback
peers. It is not a real-account host, authenticated permission or secure OS handoff.
See [interactive synthetic acceptance](../dotnet/Lala.Cloud.Acceptance/README.md#interactive-terminal-synthetic-acceptance).

## Opt-in interactive role selection

Pass `roleSelector: IAccountRoleSelector` to `AccountLoginPreparation` or
`AccountConnectionRuntime` (also forwarded by `AccountRuntime.Create`) before starting the login. The preparation's frozen disclosure
then has `RoleSelectionMode.Interactive` and `FixedRoleIndex == null`; otherwise it retains
fixed selection with `FixedRoleIndex == Profile.RoleIndex`. In interactive mode the legacy
profile role index is only a compatibility placeholder, never a fallback selection.
The host must obtain permission for this mode before acquiring/sending credentials.
The callback is not proof of consent. Interactive runtime options require one attempt.

After formal authentication and a validated server role list, Core invokes `SelectAsync`
with immutable roles, session generation, `HandshakeAttempt` and a unique request ID. The handshake identifier is distinct from
the receive publication attempt identifier.
Return `request.Choose(index)` for an offered unlocked role or null to decline. A choice
created from another request is rejected even if its index matches. Declining, returning
an invalid choice or throwing ends the attempt with `EventHandlerFailed`; callback
exception messages are not published. There is no role fallback or retry. Empty, duplicate,
locked-only or invalid role lists fail closed. No game-command send API is introduced.

The callback runs outside lifecycle locks and outside the receive writer. The existing
single decoder continues receiving and replying to heartbeats while selection is pending;
protocol observations and the eventual selection write remain serialized. Stop, session
replacement, protocol failure and the login deadline invalidate late choices. Completion
and disposal include the callback's completion, so a callback that ignores cancellation
keeps cleanup pending rather than being abandoned. Hosts should honor its cancellation
token and must not await disposal from inside their own callback.

Validation uses synthetic credentials and loopback peers only; it does not establish
live-server acceptance or change Desktop behavior or resource/gameplay holds.

## Prepared integrated resource lifetime

For the shared-Core account that also owns resource acquisition, inventory and
catalog publication, use `AccountRuntime.CreatePrepared`, rather than extracting
or recreating a connection from `AccountLoginPreparation`. The integrated
runtime exposes separate `Disclosure.Login` and `Disclosure.Resources` objects
before Run, and requires independent host authorization for both scopes. It uses
one prepared connection, the same interactive role callback contract, and the
existing aggregate status/publication/cleanup lifetime. See the
[prepared integrated contract and current verification limits](dotnet-account-connection-runtime.md#prepared-integrated-account-lifetime).
This does not change the connection-only acceptance runner or install a real host.
