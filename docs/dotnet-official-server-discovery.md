# Core official server candidate discovery

`Lala.Core.Sessions.Discovery.OfficialServerDiscovery` adds a public, read-only
metadata boundary. It is not login readiness or official-server acceptance.
There are no UI, account, credential, transport-profile, database or inventory
changes in this component.

## Explicit use

```csharp
using var discovery = OfficialServerDiscovery.Create();
var snapshot = await discovery.RefreshAsync(cancellationToken);
if (snapshot.TrySelectLine(chosenLineId, out var candidate))
{
    // Display/review candidate.Host and candidate.Port only.
    // A line selection does not authorize connecting or transmitting credentials.
}
```

Construction is inert: no network, environment lookup or disk access. There is
no default selected line or bundled list. The optional factory host must be
exactly `wlreftpsrc.chinesegamer.net` or `wlreftp.chinesegamer.net`; arbitrary
URLs, ports, credentials, handlers, sources and evidence claims are not public
inputs. The caller explicitly invokes each refresh. There is no polling,
background monitor, retry of the server list, or persistent cache.

One refresh can run at a time. `Current` is the last successful immutable
historical snapshot. A failed refresh preserves it; a retained snapshot has no
freshness TTL and is never authority. Disposal clears `Current`, cancels owned
HTTP operations and attempts all owned cleanup. The caller must also await any
in-flight `RefreshAsync`; synchronous disposal does not claim to have joined
that task. Cancellation or disposal prevents late publication. Cleanup failure
is sanitized, blocks reuse and is not silently reported as success.

## Acquisition and identity

Each refresh performs these steps:

1. Reuse `HttpOfficialResourceSource.ObserveAsync` to observe `ResourcePath_PC.dat`
   and the `DataPackage` and `MainPackage` versions.
2. Request exactly
   `https://<selected-host>/WLN/TW/<observed-data-version>/ResourcesPC/ServerList.txt`.
3. Observe the official versions again and require equality of the data version,
   executable version and both complete package identities. Timestamp equality
   is intentionally not required.
4. Validate all candidate rows and publish only after request cleanup succeeds.

The server-list transport accepts only HTTP 200 at the identical original URL.
It disables redirects, automatic decompression and cookies, does not set
credentials, rejects encoded bodies, bounds headers to 16 KiB and bounds the
body to 64 KiB including a one-byte overflow probe. Declared length, when
present, must be valid and match the body. Each request has a 12-second timeout,
including body reads; caller cancellation and source disposal also cancel it.
The version observer retains its existing narrowly constrained version-endpoint
query, canonical-retry and same-path redirect rules. The server-list fetch has
no such retry or redirect allowance. Existing resource `OpenAsync` URL access
has not been widened to include the list or arbitrary files.

`ContentSha256` hashes the received bytes. `CatalogIdentity` is the Python
server-list identity: SHA-256 of the ASCII exact URL, one NUL byte, then the raw
body. UTF-8 BOM bytes remain part of identity. These hashes provide byte
identity, not publisher authentication.

Only the public production factory can produce `TlsOriginObserved=true`, after
successful requests through the built-in HTTPS transport. This means the
ordinary operating system TLS trust chain and allowlisted resource origin
were observed. It does not mean publisher signatures were verified. Internal
injected handlers and sources are exclusively for offline tests; even if they
return identical origin strings and bytes, snapshots from the offline factory
always have `TlsOriginObserved=false`.

## Strict parser and conservative address scope

The parser follows `wlre/services/official_server_list.py` and
`wlre/storage/server_lines.py` for the supported subset:

- Strict UTF-8, optional BOM, JSON array of 1–256 object rows.
- Unique integer IDs in 1–65535 and required names of 1–120 Unicode characters.
  Duplicate JSON property names (including escaped aliases) are rejected.
- Real group IDs are 1–99. Every line ID above 100 must reference such a group
  with `id / 100`; another line cannot stand in for a group. ID 100 is rejected
  rather than silently ignored. At least one line is required.
- Each line requires `address` and an integer port in 1–65535. There is no
  hostname lookup or fallback to a `host` property. Results are sorted by ID.
  Display labels remove ASCII controls, cap group names at 60 Unicode characters,
  and use the Python group/line format.
- Only canonical four-octet decimal IPv4 literals are supported. Shortened,
  packed-integer, octal, hexadecimal, leading-zero, whitespace, URL, CIDR and
  host-with-port forms are rejected before address classification.
- Private, loopback, unspecified, shared carrier-grade NAT, link-local,
  documentation, benchmarking, multicast and reserved/broadcast ranges are
  rejected. The entire `192.0.0.0/24` and deprecated `192.88.99.0/24` ranges are
  conservatively rejected, even where a Python version may classify particular
  exceptions as global. Multicast is rejected regardless of Python's
  `is_global` behavior.

All IPv6 is currently unsupported, including global unicast, mapped IPv4,
transition addresses and scoped addresses. This is a deliberate fail-closed
subset, **not exact Python `ipaddress` parity**. An official list introducing
IPv6 or a conservatively excluded exception fails the whole refresh and needs
review; the component never silently drops questionable rows.

## Verification and authorization limits

A server-list line is a **game endpoint candidate**, not proof that it is safe
to authenticate against. Downloaded resource metadata does not establish the
historical verification server's endpoint or protocol identity. Discovery
therefore supplies no verification endpoint, account profile, credentials,
login operation, game TCP connection or credential-transmission approval.

`VerificationEndpointVerified`, `PublisherSignatureVerified`, `CanLogin` and
`CanSendPackets` remain false. Explicitly selecting a line also leaves those
boundaries unchanged. Resource catalog admission, account authentication,
verification endpoint review, user authorization for transmission and live
server acceptance are separate requirements.

The tests under `Lala.Core.Tests/Sessions/Discovery` use synthetic bytes and
injected handlers only. They cover malformed rows/addresses, duplicate fields
and IDs, unsupported groups, exact URL/status/redirect checks, version races,
size/header bounds, cancellation, timeout, concurrent refresh, disposal and
throwing cleanup. They do not establish official-host availability, observed
live rows, real account login or any live-server acceptance result.
