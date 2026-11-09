# Desktop login integration — overall PR 8.0.44

The Avalonia login and role controls use shared Core preparation. The Python-compatible
server/line dropdowns now load official HTTPS metadata through `OfficialServerDiscovery`.
Protocol bytes and the verification endpoint come from the reviewed Python release profile,
never editable text fields or downloaded rows. Unknown executable versions/groups, failed or
stale catalogs and no selection block admission. See [the full parity inventory](DESKTOP_PYTHON_PARITY.md)
for provenance, limitations and the remaining UI work. Credentials are never persisted.

## User flow and transport risk

0. Startup opens the separate version/resource window. It queries official metadata and can
   inspect a user-selected local resource root read-only. This is not full resource activation;
   local self-consistency cannot admit login. Continue requires fresh supported metadata.
1. Select a server and line from the verified current catalog, then enter credentials locally.
   Changing the server/line or refreshing clears both credential fields.
2. Press Login. The controls freeze for this attempt; input transfers into Core-owned
   transient buffers and both credential text fields clear. Profile changes require a new attempt.
3. Confirm each credential transmission separately: verification recipient, then formal
   recipient. Each dialog names the exact IP:port and warns that raw TCP has no TLS and
   fixed XOR is reversible, so observers may recover account/password. Closing or declining
   aborts. Both admissions must occur within the preparation's one-minute validity.
4. Select an unlocked server-provided role explicitly, then press Confirm role. That action
   authorizes this request's role-selection send and continuation of the disclosed world-login
   ACK/heartbeat protocol. Core's two-minute login deadline still applies; no default is sent.
5. The dashboard opens only after Core reports completed login protocol and publishes a player.
   Optional resource preparation uses the integrated runtime after protocol login; see
   [resource integration](DESKTOP_RESOURCE_INTEGRATION.md). Every general game command remains unavailable.
6. Disconnect, close, or application quit cancels and awaits Core cleanup and pending callbacks.
   The presentation snapshot is reset; another attempt needs fresh input and confirmations.

No credential is written to settings, logs or process arguments. Core clears owned byte
buffers; clearing Avalonia text cannot promise immediate erasure of immutable .NET strings.
Exceptions are rendered as fixed generic status text rather than copying arbitrary exception
messages. Account presentation uses a fresh opaque identity, not a stored account name.

## Boundary and review

`IAccountLoginSendConfirmation` is optional for existing host compatibility. Desktop always
installs it. The callback runs outside lifecycle locks, before each actual credential-write
admission. Core rechecks cancellation, generation, expiry, recipient and leg after callback
completion. A late approval cannot revive an ended attempt; disposal awaits even a late
callback. The existing credential leases and transport retirement retain ownership of packet
cleanup. The selector remains bound to one server request and disallows locked roles.

Source review covered duplicate click prevention, disabled profile edits, credential clearing,
per-leg confirmation, cancelled/late replies, manual role choice, UI-thread callbacks,
awaited close/stop, stale publication rejection and held game-command state. No independent
reviewer or production acceptance is claimed.

## Previous 8.0.41 validation (historical)

- Complete Core: 45,096 passed; login-focused subset: 78 passed (including seven new
  decline/failure and late-approval retirement cases).
- Public Core consumer: passed. Android lifecycle: 76 passed. Python release/preflight: 31 passed.
- Desktop offline: inspector 9 + presentation 54 passed.
- Real Avalonia Linux UI under Xvfb: 142 existing/adapted checks, plus 11 loopback login
  assertions; 16 screenshots rendered and login layout inspected.
- Loopback UI drives actual buttons and dialogs through verification, formal login, manual
  role selection, world ACKs, Core publication, stop, and closing a pending confirmation.
  Only explicitly synthetic credentials and ephemeral 127.0.0.1 listeners are used.
- CI now runs the UI/loopback suite on Linux in the existing .NET workflow. Cross-platform
  CI and native Windows/macOS/official-server acceptance are separate evidence.

No real-server connection or general game instruction was sent during this work. Do not
interpret offline/loopback success as secure transport, resource readiness, official endpoint
verification, successful live authentication, or complete game-state support.
