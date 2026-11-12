# Verified bundle cache population and read-only reuse

The resource owner reuses Python-compatible bundle cache files during bootstrap and ordinary
refresh. Bootstrap also saves newly downloaded, verified bundle snapshots after independent
inventory readback succeeds. Ordinary `RefreshAsync` remains strictly read-only: it does not
create cache directories, populate missing entries, repair corrupt entries or write inventory.
Construction still performs no network or filesystem I/O.

The fixed path is `official_sync/bundles/{package}/{package_version}/{md5}/{name}` under the
absolute data root, matching `BundleSpec.cache_path` in `wlre/services/official_bundle_download.py`.
Every component comes from the validated current manifest. No cache index, receipt, schema,
background task, eviction or additional source request is introduced. The byte/file limits
apply per prepared batch, not to all historical version directories on disk.

## Read and preparation boundary

Cache paths are only candidate locations. The unchanged preparation pipeline obtains fresh
source observations and manifests, verifies length, MD5 and little-endian CRC32, then reopens
and verifies selected cached bytes before extraction. Missing or corrupt initial content is a
cache miss; normal download quotas apply. A selected cache entry disappearing or changing
later fails the attempt rather than silently adding an unbudgeted download. Access and other
I/O failures are not swallowed. The 32 MiB aggregate retained-source bound applies to cache hits
and downloads alike; downloads still obey the existing 24-file / 32 MiB ceiling.

Prepared results retain immutable references to the privately owned `VerifiedBundleSource`
snapshots for required tables and successfully decoded optional features, including their real
manifest dependencies. Shared bundles are retained once. Failed optional decoding does not
retain an additional optional-only closure just to populate the cache. A dependency first
acquired for a rejected feature may still be retained if an accepted feature needs it. No
bundle is reopened from its original response or an unchecked cache path to obtain write bytes.

## Bootstrap write and admission ordering

Bootstrap keeps its existing inventory baseline, write transaction, truthful storage receipt,
and independent read-only table matching. Only after required readback matches does it pass
the prepared snapshots to the cache writer. Cached acquisitions are not rewritten; only owned
verified downloads are candidates for population. The final fresh version and complete-manifest
recheck follows all cache disk work, before publication, without another round of source calls.
Cancellation and owner currentness are checked around cache work and at final publication.

The writer bounds and snapshots the supplied batch before filesystem changes. Each missing or
corrupt destination is staged in a unique same-directory file, flushed, closed and independently
checked against the owned length, MD5, CRC32 and SHA-256 before atomic replacement. Successful
completion requires checking installed bytes again; cancellation/failure after replacement
may interrupt that last check. A matching existing file is left unchanged, including when
another cooperative writer installed it while staging. The writer rejects directory
destinations and observed symbolic links/reparse points at the selected data root and below;
platform aliases above that root remain part of the caller-selected filesystem. Path checks
are not a sandbox against hostile concurrent filesystem replacement, nor a general filter for
POSIX special files. Ordinary operating-system rename and sharing semantics apply. No directory
fsync or power-loss durability guarantee is claimed.

A later source change, cancellation, invalidation or cache I/O failure prevents publication but
does not undo an already committed inventory or an already published cache file. Cache failures
remain visible in the owner's existing `Failure` result, with the independent database receipt,
`Committed`/`Unknown` outcome and readback status preserved. A batch is not an all-or-nothing
transaction and no compensating deletion or rollback is claimed. Only a writer's own staging
file is cleaned up; cleanup failure remains observable. Version-keyed files left by a failed
attempt are still untrusted candidates on the next attempt.

Optional bytes that decoded successfully may be cached even if independent database matching
subsequently removes that optional feature. This never restores feature availability: every
later preparation still extracts/decodes current source bytes and matches the database anew.
Cache contents cannot grant provenance, inventory admission, account authority, login or packet
permission. Source observations remain mandatory; this is not an offline-startup mode.

## Offline coverage and verification limits

Synthetic cases cover fresh bootstrap followed by refresh without bundle downloads, corrupt
cache repair during bootstrap only, missing/corrupt-cache refresh without writes, unchanged
cache hits, exact owned bytes after mutable source-buffer changes, and cache disappearance
between planning and acquisition. Separate optional-only bundles exercise accepted closures,
shared dependencies, rejected optional decoding and readback-rejected feature availability.

Failure/lifecycle cases retain committed database outcomes across cache I/O failure,
cancellation, invalidation, disposal and final source drift, without publication. A partial
batch case leaves a previously installed valid file in place when a later destination fails.
Writer cases exercise staging, verification, bounds, cancellation and filesystem rejection.
Symbolic-link cases exercise Unix behavior; they do not establish Windows reparse-point behavior.
No official network, real credentials or user database is accessed. These additions require
focused and combined-head verification; previous read-only-cache results do not establish the
new write path or live acquisition.

Local verification on cloud .NET 10.0.403 passed 2,780 resource/session cases, followed by
all 43,294 Core tests on the final rebuilt tree, with no test-run skips. Unix link cases
remain conditional and do not exercise Windows reparse behavior. Two fixture issues were
corrected during verification: an omitted cancellation argument and cleanup of a dangling
Unix directory link. Production behavior was unchanged by those corrections. Deterministic
contention cases also verify that a competitor's valid destination survives another writer's
cancelled or corrupt staging. Independent review found no remaining blocker within the stated
filesystem scope. Platform builds and exact published-head CI remain separate checks.
