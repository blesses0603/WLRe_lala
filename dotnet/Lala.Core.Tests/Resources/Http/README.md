# Uninstalled resource HTTP acquisition

`HttpOfficialResourceSource` is an internal implementation of the neutral
`IResourceSource` seam. It is not registered anywhere, installs nothing, and
cannot issue provenance, readiness, runtime admission or packet permission.
Scripted sources remain test scripts. The same checksums and fresh observations
are evidence, not publisher signatures or authority tokens.

Production construction owns a narrowly configured `SocketsHttpHandler` and
`HttpClient`: normal TLS validation, no credentials/cookies/automatic redirects
or automatic decompression. Test construction owns an injected fake handler;
these tests never contact an official service. It does not accept arbitrary
preconfigured clients or read environment variables. Its one selected host is
bound to the preparation host before observation. There is no host fallback.

Original URL text must match the selected HTTPS origin with no explicit port,
userinfo, fragment, percent encoding, backslash or whitespace. Resource paths
are exact map/package paths or constrained bundle filenames. Only version
requests allow numeric cache-busters. Manual version redirects are limited to
three, on the same host and exact path, with constrained relative forms.
Only 400/403/404 receive one query-free canonical retry. Manifests and bundles
never redirect or retry. A transport failure never falls back to cached metadata.

Response headers are bounded to 16 KiB, versions to 16 KiB, hashes to eight
bytes, manifests to 8 MiB and resource streams to the existing 32 MiB retained
closure cap. Existing preparation still enforces exact bundle sizes, CRC/MD5,
parsed manifest identity and aggregate 24-download/32-MiB quotas. Content-Length
is strict ASCII decimal and checked against actual bytes. Automatic decoding is
disabled; only resource-map gzip is explicitly parsed with a bounded output,
one member, exact trailer length, CRC and ISIZE verification. Raw gzip framing
uses one-byte compressed reads to prevent read-ahead hiding a second member.

Linked timeouts (12 seconds version; 20 seconds resource) cover headers AND the
entire returned body lifetime. Caller cancellation stays cancellation. Returned
streams own their response and timeout source; the source owns its client and
handler. Dispose responses even on read failure. Exceptions expose stable
categories, never remote URLs, headers, body text or inner transport exceptions.

Raw-version fixtures execute the retained Python parsers, rather than replacing
them with a duplicate oracle. Fixture source hashes normalize CRLF only.
`python dotnet/Lala.Core.Tests/Resources/Http/generate_http_vectors.py --check`
checks deterministic output. The C# tests also pin those hashes. Bounded malformed
input handling may be stricter than Python (JSON depth and HTTP headers); no
stricter rejection broadens source acceptance.

Offline fake-handler tests include full manifest -> owned bundle -> Unity
extraction -> all ten decoders -> final source reobservation. Version change,
same-version manifest replacement, cancellation, URL rejection, redirect loops,
canonical retry, length bounds and disposal failures are exercised. Completion
remains non-ready and non-authoritative.

Run the focused test class and then all Resources tests and the complete Core
suite using the repository's serialized compiler workflow. No live HTTP test is
part of this slice. Device/server/TLS-network acceptance remains untested.

The snapshot workflow follows `official_resource_sync.observe_official_versions`,
not the broader `official_version.check_official_game_resources` UI checker.
In particular HTTP 200 with invalid HTML/XML/JSON is rejected without a second
canonical request; that broader checker's InvalidResourceBody retry is excluded.

Validation for this slice: Release compiled without warnings/errors; focused
HTTP tests passed 86/86, impacted Resources tests passed 687/687 (no skips).
The retained Python reference suites passed 44/44; fixture `--check` and
`git diff --check` passed. Independent static review found no confirmed blocker.
The integrating task owns the complete combined Core regression.
