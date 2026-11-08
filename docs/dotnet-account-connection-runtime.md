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
