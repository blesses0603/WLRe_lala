# Owned ten-table inventory bootstrap

`ResourceRuntimeOwner.BootstrapAndRefreshAsync` is an internal, uninstalled shared-Core
composition. It connects existing source acquisition, extraction and ten-table decoding to
`ResourceInventoryStore`, then an independent read-only snapshot and the existing matcher.
`RefreshAsync` stays read-only: it does not create directories, databases or missing schema.
Neither method is called by a UI, Android service, login or packet sender in this increment.

## Source mapping and deliberate scope

- `wlre/services/world/resource_database.py:13–197` is the inventory primitive: select logical
  `tables/...*.bytes` basenames; record canonical identity; keep immutable same-version raw and
  derived rows; retain omitted rows; update active/previous/parent inventory references; commit
  one operation. The existing bounded six-table Core store implements that primitive.
- `resource_rebuilder.py:668–679` invokes that writer before archive construction, once its
  selected asset set has no missing entries. The archive-specific lock, `.partial` ZIP,
  readback and `os.replace` occur later at lines 738–766. There is no source SQLite staging
  database. This composition creates no ZIP, temporary database or new schema.
- The Python rebuilder selects all supported assets. This composition intentionally prepares
  only the ten required runtime tables. It is new orchestration of source-derived primitives,
  **not complete resource-rebuilder parity**. The receipt's table differences describe those
  supplied ten tables; they do not establish absence across the full supported asset set.
  Omitted same-version tables remain stored. Static 1275 release pins/count gates, optional
  tables/images/indexes, full archive publication and runtime installation remain separate.

## Owned inputs and production boundary

`OfflinePreparedRuntimeCandidate.InventoryInput` retains detached copies of the exact native
TextAsset arrays at logical `tables/<name>.bytes` paths. These are not reserialized catalog
objects. The identity comes from the actual observed and parsed package manifests. Capture
recomputes every SHA256 and compares it to the real ten-table decoder's computed hashes before
return. The 16 MiB per-table and conservative 32 MiB aggregate extracted limits are unchanged.
Raw-table copying transiently retains more than one bounded copy; provider/native buffers and
CLR object overhead are not included in those payload limits. Existing source/download and
parser quotas also remain mandatory. Missing paths, decoding errors and quota failures occur
before directory creation or storage.

Production `Create(dataRoot)` accepts no source, provider, payload, identity, digest or callback
claims. It lazily owns `HttpOfficialResourceSource` and concrete Microsoft.Data.Sqlite
connections. Bootstrap creates only the fixed parent directory and opens
`official_sync/derived_catalogs/resource_inventory.sqlite3` using ReadWriteCreate, private cache,
no pooling and the existing command timeout. It does not repair, replace or reset a malformed
or colliding inventory. Path containment is lexical, not symlink/hostile-filesystem protection.
No live source or game/user database was accessed to validate this implementation.

Offline construction permits instrumented sources and connection wrappers solely for tests.
Even fully fabricated offline provider results cannot obtain resource/TLS admission. Production
TLS means ordinary OS trust, not a publisher signature or protocol-compatibility proof. No
publication or receipt authorizes login or packets.

## Commit admission, readback and lifecycle

Both methods use the same owner attempt, generation, invalidation and disposal machinery. One
attempt stays occupied through the entire write, readback, final reobservation and cancellation
callback retirement. A later call is rejected while it is running or retiring; invalidation
revokes publication immediately but does not release the writer slot. This prevents an older
writer from overtaking a newer attempt **in the same owner**. There is no cross-owner/process
serialization or filesystem replacement claim. A later increment adds an optimistic active
selector/identity precondition across independent owners before inventory DML; see
[write concurrency](../../../../../docs/dotnet-resource-inventory-concurrency.md).

After all store DML/report/integrity work and COMMIT command construction, the owner performs
one final admission check under its publication gate. It checks the exact attempt, generation,
disposed state, original caller token and synchronous cancellation-requested flag, then marks
commit admitted. There is no SQL, provider call, callback or await under that gate. Production
runs uncancelled COMMIT immediately after the check. Revocation before admission prevents
COMMIT and takes the store's rollback path. Revocation racing after admission may leave
Committed storage, but the revoked attempt never publishes.

The writer and all its commands/readers must finish cleanup before a distinct ReadOnly
connection is created. The reader uses its own explicit read transaction, detaches the active
identity and actual ten BLOBs, disposes its read scope, and the matcher hashes those actual
bytes against the prepared identity/digests. A write receipt is not readback evidence. Both
complete manifest bodies and the version endpoints are reobserved again afterward, across
readback. Cancellation registration/callback cleanup completes before final gated publication.

The existing fail-fast self-disposal guard still applies to direct callbacks and flowed
execution contexts. Real disposal remains externally joinable until the source and entire
attempt retire. It is not a general cross-thread wait-graph detector: custom callback
marshaling that discards that context can create unsupported self-wait cycles.

## Honest historical outcomes

`BootstrapAndRefreshAsync` returns an immutable historical result after an admitted attempt:

- `StorageAttempted`, `StorageOutcome` (NotCommitted, Committed or Unknown), `CommitAdmitted`
  and an optional clean `Receipt` preserve the storage outcome independently of publication.
- `Readback` distinguishes NotAttempted, Failed and Matched. `SourcesRechecked` describes the
  final source observation; neither is inferred from a successful store write.
- `Publication`/`WasPublished` describe historical publication; reacquire `Current` and its
  dynamic admission check to determine whether it remains current. `Failure` retains the
  original/combined write, readback, cancellation, source or cleanup exception.

Busy/disposed admission rejects before creating an attempt and still throws. Once admitted,
failures, including cancellation, are returned as data rather than pretending a confirmed
commit was rolled back. Post-COMMIT command/connection cleanup failure is Committed even though
no clean receipt is returned. An unacknowledged COMMIT execution remains Unknown even if the
store's existing cleanup ROLLBACK succeeds. That cleanup resolves any still-open transaction;
there is no owner-level compensating write, rollback of committed contents, reset, delete or
automatic retry after uncertainty. A later explicit request must inspect fresh storage again.

`RefreshAsync` preserves its previous throwing, read-only API and uses this same lifecycle.
An ordinary read-only refresh can still fail while a previous bootstrap's storage stays intact.

## Offline verification

The new regression suite uses the retained synthetic UnityFS bundle fixtures and actual
isolated temporary SQLite databases, with existing provider wrappers for deterministic faults.
It checks the fixed six-table format, exact ten rows, independently reopened ReadOnly readback,
idempotence, retained unrelated tables, identities/parents/previous state, immutable collisions,
forged recorded hashes, schema/triggers, missing/malformed/oversized sources, owned bytes,
revocation before/after commit admission, uncertain execution and confirmed cleanup failures,
readback tampering, final manifest/version drift and joined writer/callback retirement.
Existing read-only owner tests are intentionally unchanged. No game payload, credentials,
private installation path, actual network acceptance, platform/AOT acceptance or complete Core
migration is claimed by these tests. Verification counts are recorded after the final run.

## Recovered-work validation (2026-11-08 UTC)

- Existing recovered bootstrap/owner focused selection: **68 passed**, no failures or skips.
- Added one deterministic caller-cancellation-during-final-cleanup regression. It preserves
  committed storage, matched readback and source-recheck evidence while rejecting publication,
  then verifies a fresh explicit read-only refresh can reuse that inventory after retirement.
- Final full Core run: **41,546 passed**, no failures or skips, with a process-only 3 GiB
  `DOTNET_GCHeapHardLimit`. The preceding standard-settings run was aborted by a test-host
  crash; it is **not** recorded as passing. No assertion, case, parallelism or CI policy changed.
- Android lifecycle: **59 passed**. Desktop Release build: **0 warnings/errors**; offline
  inspector: **9 checks passed**. These ran only in the recovered cloud workspace.
- Existing Python suite: **2,273 total, 216 skipped** under its existing platform conditions,
  no failures. Strict repository audit passed; six audit tests passed. Xvfb was unavailable,
  so GUI/native/device acceptance is not claimed.
- Independent read-only review found no blocking issues in the recovered implementation or
  the added regression. Live HTTPS, game-server access and actual user databases were not used.
- This receipt is local evidence only. Remote standard-settings CI and Android APK/native
  packaging for these unpublished changes have not yet been verified.
