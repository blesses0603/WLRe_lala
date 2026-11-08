# Public account connection runtime

`AccountConnectionRuntime` is the host-callable Core boundary for explicit TCP login,
continuous receive, and bounded reconnect. Construction is inert. Hosts supply the
same `AccountSession`, its current generation, an explicit `AccountConnectionProfile`
and an `IAccountCredentialSource`. There is no default official endpoint, saved
password, platform credential store, Desktop adapter, or live-server validation.

The source receives a sanitized generation/attempt request and returns a fresh,
exclusively owned `AccountLoginCredentials` or null. Returning transfers ownership.
The runtime clears its account/password buffers after formal login encoding or
failure/cancellation; owned transient packet buffers are also cleared. It cannot
clear the caller's original strings/spans, prevent managed-memory copies outside its
control, or make the raw TCP protocol secure. Protocol XOR is not encryption.
Never put credentials in exceptions or logs. Source objects remain caller-owned.

`RunAsync` is one-shot; its first cancellation token owns the lifetime. Repeated
calls return the same task. `Stop` immediately revokes further connection/write
admission. Completion/disposal waits for admitted callbacks, including a source
that ignores cancellation; hosts should honor cancellation and marshal prompts to
their own UI thread. A late credential result is disposed, not sent. Cleanup failure
is represented by a sanitized result or `AccountConnectionCleanupException`.

One attempt is the default. Set `MaximumAttempts` explicitly if Core owns retries;
do not nest this inside another automatic retry policy. Each attempt requires fresh
credentials. Only classified safe connection failures or completed-login read/EOF
failures, including typed formal read timeouts, can retry after successful cleanup.
Read timeouts before completed login, uncertain writes, malformed protocol and
provider failures remain terminal. Account replacement or an explicit hold stops recovery.

The C# read timeout intentionally retires the connection; it is not Python-style
idle polling or a new keepalive. Recovery uses a fresh connection and credentials,
requires an explicitly configured multi-attempt policy, and can exhaust that budget
after repeated quiet periods. The default remains one attempt. No production
heartbeat interval or live-server compatibility is inferred from this policy.

`Snapshot` exposes bounded, sanitized lifecycle history. `Publication` is current
receive state only and becomes null on stop/replacement or between attempts. State
contents are not sanitized for logging. Custom observation callbacks run on the
receive writer, not the UI thread.

Successful protocol login still means `ReceivingHeld`: resource and game-command
authority are not granted. There is deliberately no command-send API. The separate
`AccountResourceRuntime` can prepare/read catalogs for the same session without
unholding it. Its exact snapshot binding may be invalidated by connection attachment
or reconnect; refresh explicitly against the stable latest session afterward.

## Verification

The public-only TCP tests use synthetic loopback peers, not a production server.
The separate `Lala.Core.PublicContract.Check` executable has no friend-assembly
access and exercises inert construction, cancellation, credential construction,
and the resource facade without network or resource writes:

```
dotnet run --project dotnet/Lala.Core.PublicContract.Check -c Release
```

The CI desktop matrix runs this consumer check in addition to the full Core suite,
Android lifecycle suite, and existing Desktop build/self-tests. No Desktop UI or
Android host integration is implied by this API boundary.

## Optional one-attempt preparation

`AccountLoginPreparation` privately composes the exact profile, selected identity marker,
current session snapshot and one input acquisition with per-credential-leg write admission.
It does not authenticate permission or install an input host. See
[preparation binding and limits](dotnet-account-login-preparation.md). Existing direct
runtime callers retain their own authorization, retry and credential-source responsibilities.

### Prepared integrated account lifetime

`AccountRuntime.CreatePrepared(session, generation, selectedIdentity, profile,
input, absoluteDataRoot, options, validity, roleSelector)` is the prepared route
for a long-lived account with receive state and resources. Construction is inert.
Before `RunAsync`, the host must independently obtain permission for **both**
`runtime.Disclosure.Login` and `runtime.Disclosure.Resources`. The login disclosure
names the exact raw-TCP recipients and interactive/fixed role mode. The separate
resource disclosure gives the normalized absolute data root, fixed SQLite
inventory and bundle-cache paths, official HTTPS version-map URL, and the prefix
within which validated, version-dependent metadata/bundle URLs are resolved.
Login permission does not authorize resource acquisition or local writes.

This composition owns the same single prepared connection, input, role selector,
and resource lifetime; it does not export reusable credentials or a raw source.
Preparation is bound to the exact session snapshot, one attempt, and a validity
window of at most one minute. Both credential writes must be admitted within
that window. After formal credential admission, expiry does not end a healthy
receive-only session. Resources start only after protocol login. They use the
existing inventory bootstrap/readback, catalog publication, observation
projection and cleanup paths. The session and all publications remain Held with
no game-command authority, including after successful resource binding.

`Snapshot`, `WaitForChangeAsync` and `Publication` retain the normal integrated
account contracts. `Stop` synchronously revokes prepared admission and visible
resource selection, and asynchronously drains owned work. Completion/disposal
wait for late input, selector and resource callbacks; cancellation alone does
not establish cleanup. Completed cache/inventory writes are not rolled back.
Session replacement or same-generation snapshot changes invalidate this
preparation. A replacement requires new disclosure and permission. Repeated
`RunAsync` calls return the original task, never another login.

The existing `AccountRuntime.Create` raw-source route remains available as a
legacy explicit composition. It does not provide prepared admission or a
combined disclosure. No desktop or Android host is connected by this API change.
Synthetic loopback and injected-resource tests are wiring evidence only, not
real credentials, official resource provenance, live acceptance, or permission.

#### Resource admission and verification status

Each scheduled preparation captures its resource revision while the account
lifetime gate is held. Resource admission checks that revision and the exact
session snapshot, then synchronously reserves the owner's attempt. Reservation
performs no I/O, source callback or cancellation registration under those gates.
Execution happens outside them and rechecks the owner epoch before proceeding.
Invalidation/disposal can therefore see and drain even a reserved attempt whose
execution has not started; a delayed preparation cannot silently become a new
attempt after retirement. Already-admitted work and completed writes are not
promised rollback.

Offline validation was resumed after the earlier cancelled full run. The final
executable source, including resource revision/reservation and the one-shot guard,
passed the following serialized Linux checks on 2026-11-08:

- Focused prepared/integrated/reservation regressions: 26 passed, 0 failed.
- Full Release Core suite: 43,364 passed, 0 failed, 0 skipped.
- External `Lala.Core.PublicContract.Check`: passed, including fixed/interactive
  prepared disclosure, pre-cancellation, status waiting, one-task reuse and
  disposal-before-Run. It requested no network or resource writes.
- Android lifecycle suite: 76 passed, 0 failed, 0 skipped.
- Cloud acceptance synthetic self-test: 36 passed, 0 failed.
- Actual Linux terminal PTY checks: 17 cases passed, including redirected streams
  and hangup during acknowledgment/password input.

The deterministic resource regressions cover stale scheduled revisions before
owner reservation, invalidation/disposal between reservation and execution, and
duplicate execution while the first attempt is blocked. They assert no source,
callback or storage work can be admitted through the retired reservation and
that disposal waits for its cleanup. Package restoration used the local cache.
These are synthetic/loopback and retained-fixture results, not official resource
provenance, real-account acceptance, or Windows/macOS terminal verification.
Successful catalog binding remains an explicitly white-box synthetic-source
wiring check. No Desktop/Android host has been wired to this route.

Construction validates/normalizes the root before creating the preparation, and
validates session, profile, identity, input, options and validity before creating
production resources. It starts no provider/selector callback, timer, connection
or resource operation. `IAccountLoginInput` and `IAccountRoleSelector` are host
callbacks, not disposable objects whose ownership is transferred by construction;
Core owns and clears credentials returned by input. The host remains responsible
for clearing its original input buffers and for its own callback objects. If
factory construction throws, no runnable account is returned and no login or
resource operation has been admitted.
