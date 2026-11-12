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

## Cleanup failure contract

Cleanup is not assumed successful merely because disposal began. Source disposal
attempts cancellation, client disposal, independently owned handler disposal and
CTS disposal even if an earlier action throws. Response disposal attempts its
response/content, falls back to an already-acquired body if response disposal
throws, and still retires the request lifetime. It does not read a rejected body
just to obtain an inaccessible nested resource for cleanup. Such failures remain
explicitly incomplete rather than claiming every nested resource was released.

Any incomplete cleanup produces a stable `ResourceTransportException(Cleanup)`
after the remaining attempts, without hostile exception messages or inner
exceptions. Failed repeated disposal still fails. A concurrent/reentrant call
while disposal is in progress fails explicitly instead of returning false
completion or waiting into a callback cycle. Successful completed disposal is
idempotent. `CleanupIncomplete` is additional sticky evidence, not a substitute
for the failure. `DisposalAttemptsComplete` describes source-owned attempts only;
returned responses remain their caller's responsibility.

The HTTP version-read and open-failure scopes and bundle preparation's response
scope explicitly preserve an existing primary error. They attach only
`Data["resource_cleanup_failure"] = "Cleanup"` if finalization also fails. An
arbitrary external caller's own `using` block cannot automatically preserve its
pending exception when Dispose throws; that caller must use the same explicit
primary-preserving pattern if needed.

Request timeout no longer uses unguarded `CancelAfter`. Each request owns a
tracked lifetime with guarded caller/shutdown cancellation forwarding and a timer.
Throwing user cancellation callbacks cannot escape the timer thread. Disposal
stops future callbacks, unregisters forwarding and waits for admitted cancellation
callbacks to finish before disposing the CTS. No internal lock is held while
calling arbitrary cancellation/disposal code. A cancellation callback attempting
to dispose its own lifetime receives explicit Cleanup/pending failure; final CTS
cleanup is deferred to that callback's exit rather than waiting on itself. A
failed timer/registration disposal also remains incomplete, even if the stopped
entry gate prevents later queued callbacks from touching the CTS.

Cleanup regression validation: Release compiled cleanly; 12 cleanup tests passed
in the initial focused run and three consecutive repeats; all 785 impacted
Resources tests passed with no skips. No unhandled timer-thread exception or
reentrant deadlock was observed. The blocking/reentrant tests use deterministic
entry gates and five-second assertion bounds. Ordinary cleanup deliberately
waits for admitted callbacks; it cannot force an arbitrary external callback or
Dispose implementation that never returns to terminate. This is not a claim of
a universal finite cleanup deadline. Independent static review approved the
ownership/retirement contract. Fixture and diff checks passed.

The shutdown/throwing-callback regression uses an explicit callback-entry barrier:
`Task.Delay` installs a later cancellation registration, so LIFO cancellation can
complete it and schedule handler unwinding before the earlier hostile callback
runs. The handler must not dispose that registration until callback entry is
observed. Tests assert actual invocation and retain the strict primary Cleanup
marker assertion. A separate deterministic LIFO-unregistration test proves that
a callback removed before invocation legitimately produces no callback failure;
this distinguishes the test synchronization bug from a lost production marker.
The barrier correction passed 13/13 focused cleanup tests and 786/786 impacted
Resources Release tests (no skips), after parent independent review. Both
telemetry opt-outs were set for each .NET invocation. Production cleanup code
and the strict primary cleanup-marker assertion were not changed.

## Response-callback regression synchronization

The recovered aggregate rerun exposed the same LIFO registration race in the response-disposal
case: `Task.Delay` could resume first and exit the `using` scope, unregistering the earlier
callback before it ran. This was a test-harness failure, not evidence that production disposal
completed successfully. The test now awaits a callback-finished signal before unregistering,
requires exactly one invocation, and bounds its waits. Existing timeout, incomplete-cleanup,
source-state and disposal-count assertions are unchanged; production code is unchanged.
The deterministic unregister-before-invocation test remains as the negative control.

After the fix, all **13 cleanup tests passed in four independent runs**, followed by
**41,546 full Core tests** and **59 lifecycle tests**, with zero failures/skips. The full Core
run used the documented process-only 3 GiB heap limit. Repeated runs are not extra cases.
Independent review approved the synchronization; standard remote CI remains a separate gate.
