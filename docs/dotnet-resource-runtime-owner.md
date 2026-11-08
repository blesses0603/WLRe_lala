# Uninstalled resource runtime owner

`Lala.Core.Resources.ResourceRuntimeOwner` is internal and is not connected to
AccountSession, desktop login, Android, or packet sending. Its publication records
resource admission only. Publisher signatures and protocol compatibility remain
unverified. Existing offline decoder/preparation flags remain false.

## Construction and trust

`Create(absoluteDataRoot)` owns the default constrained HTTPS source and creates a
concrete Microsoft.Data.Sqlite read-only connection only during refresh. Construction
performs no HTTP or database I/O. The fixed inventory location is
`official_sync/derived_catalogs/resource_inventory.sqlite3` beneath the root, matching
Python `resource_rebuilder._roots` and `game_version_gate._run_dynamic_check`.
Missing inventory fails closed; this owner does not bootstrap or write it.
Path normalization is lexical, not protection against symlinks, hostile local
filesystem replacement, or a compromised process. SQLite is opened without pooling,
with a private cache and read-only mode.

`CreateForOfflineTests(root, source)` exercises the same preparation, concrete SQLite
reader, byte matcher and publication sequence, but its publication always reports
resource admission and TLS evidence false. No production factory accepts a source,
handler, provider, candidate, or claimed digest map.

Default HTTPS uses OS certificate validation and ordinary OS trust roots. This is
origin evidence, not a publisher signature or proof against compromised roots or
servers. Checksums bind the acquired content; they do not provide signatures.
This first owner does not reuse disk bundle caches.

Both complete current package versions, DataVer and ExeVer must remain identical
through preparation and a final post-database reobservation. The owner does not
silently add shipped-1275 or shipped-executable equality requirements. Parser support
and exact dynamic identity are distinct from game protocol compatibility.

## Refresh and publication

Exactly one refresh may be running or retiring. Concurrent refresh calls are rejected
with InvalidOperationException rather than queued or shared. Only the accepted
caller's cancellation token controls that operation. A caller may retry after it
finishes. Invalidation synchronously clears Current and increments generation before
cancelling outside the publication lock. Old work cannot clear a later publication.

Refresh decodes owned bytes, opens the existing inventory in one read transaction,
rehashes its actual blobs against internally derived raw-table hashes, waits for DB
cleanup, then reobserves versions and manifests. The final cancellation/generation
check and immutable publication occur under one lock. No persistence or callbacks run
under that lock. ResourceAdmitted queries the owner under its lock and requires the exact current
publication reference, generation, production construction and non-disposed owner.
Fabricated/cross-owner publications and retained stale publications do not admit.
TlsOriginObserved is likewise tied to the current owner-issued publication, not merely
the kind of owner supplied to a constructor. Consumers should reacquire Current.

An explicit attempt retirement task is installed under the admission lock, before any
await. Caller cancellation forwards into one tracked cancellation worker; retirement
awaits caller-registration disposal and every cancellation callback, including throwing
or reentrant callbacks, before disposing the attempt and allowing another refresh.
The worker invokes cancellation outside the publication and attempt locks. Invalidation
and disposal revoke authority synchronously, and cancellation requests are visible at
owner boundaries immediately; source-token notification runs on the worker. A pre-cancelled
caller cannot enter the source. The original caller token is also checked at the final
publication gate.

Self-reentrant disposal has an explicit fail-fast join contract: calling DisposeAsync
from this owner's active refresh, cancellation callback or source cleanup requests
normal disposal and revokes Current, but returns a faulted ValueTask with
InvalidOperationException instead of waiting for itself or claiming cleanup is complete.
An external caller must await DisposeAsync to observe full retirement and source cleanup.
All external callers share the real pending disposal task. An uncaught self-join exception
is reported as a callback/source failure and does not skip cleanup.

Logical execution scopes flow through async source calls and captured callbacks. The
cancellation worker additionally marks its executing thread, covering directly executed
UnsafeRegister callbacks and registrations under ExecutionContext.SuppressFlow. Captured
scopes become inactive at real retirement, so later background work is not permanently
treated as reentrant.

The self-join guard covers execution on that cancellation worker and code that preserves
the owner's logical context. It cannot detect arbitrary externally dispatched dependency
cycles after that context is discarded. In particular, a callback registered with both
suppressed execution-context flow and useSynchronizationContext: true can be marshalled
to an unrelated thread; it must not synchronously join this owner's disposal. The owned
production HTTP source does not use that synchronization-context-marshalling pattern.
Ordinary external disposal still joins real retirement; it is not rejected merely because
another thread is running a callback. Cleanup cannot force a non-returning external
callback, dispatcher or source disposal implementation to terminate.

Retirement completes before another source acquisition begins. Disposal revokes
Current immediately, cancels outside the lock, waits for retirement, and disposes the
owned source. A cancellation callback exception does not skip resource cleanup.
No filesystem cache writes or cache-global mutations occur; consumers must key any
derived cache by publication generation and discard it when Current is absent.

## Dependency and verification limits

Core pins Microsoft.Data.Sqlite `[10.0.14]`, matching the existing test dependency's
version. This brings transitive SQLitePCLRaw/native SQLite runtime assets into Core's
consumers. Android restore/build/package/native-load compatibility requires actual
platform CI verification; this source change does not establish it.

The offline tests use owned bundle fixtures and temporary real SQLite databases.
They cover non-authorizing success, absent inventory, actual blob tampering,
post-database manifest replacement, cancellation, refresh-flood rejection during
retirement, disposal races and lazy production construction. Bounded callback tests cover
normal, unsafe and suppressed-flow registrations; callback-first and external-first
disposal; concurrent external joins; synchronous and asynchronous source cleanup reentry;
and captured contexts used after retirement. Callback observations are asserted by the
test itself rather than inside callbacks whose exceptions are deliberately aggregated.
These tests do not contact official servers and cannot prove successful live TLS-origin
acquisition.
