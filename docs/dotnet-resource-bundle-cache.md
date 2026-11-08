# Production read-only bundle cache reuse

The resource owner now uses existing Python-compatible bundle cache files during bootstrap
and read-only refresh. Previously its preparation always received a null cache, requiring
all bundles to be downloaded again, including on account reconnect.

The fixed path is `official_sync/bundles/{package}/{package_version}/{md5}/{name}` under the
absolute data root, matching `BundleSpec.cache_path` in `wlre/services/official_bundle_download.py`.
Every component comes from the validated current manifest. Construction does no file I/O.
No cache directories, files or receipts are written, repaired or removed.

Cache paths are only candidate locations. The unchanged preparation pipeline obtains fresh
source observations and manifests, verifies length, MD5 and little-endian CRC32, then reopens
and verifies selected cached bytes before extraction. Missing or corrupt initial content is a
cache miss; normal download quotas apply. A selected cache entry disappearing or changing
later fails the attempt rather than silently adding an unbudgeted download. Access and other
I/O failures are not swallowed. Aggregate retained-byte bounds apply even to cache hits.

All table decoding, inventory write preconditions, independent readback and final source
reobservations remain mandatory. Cache contents cannot grant provenance or account authority.
Path containment is lexical, not protection against hostile filesystem replacement. Ordinary
OS file sharing applies; this is not a filesystem sandbox or offline-startup mode. An empty
cache still downloads normally and remains empty, since cache population is not implemented.

Synthetic tests exercise successful bootstrap plus refresh without bundle downloads, retained
fresh observations, missing/corrupt-cache fallback without repair, and cache disappearance
between planning and acquisition without storage or fallback download. No official network,
real credentials or user database is accessed.

Focused Release verification passed 179/179 tests with no skips, covering owner bootstrap,
bundle preparation and native offline preparation. Existing preparation regressions also cover
same-length corrupt cache, changed reopened bytes and quota behavior. Independent source review
found no blocker. Directory/I/O-failure and cancellation behavior of the concrete filesystem
reader have not received dedicated new integration tests. Full combined-head verification is
separate; this result does not establish live acquisition.
