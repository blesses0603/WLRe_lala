# Complete, internal inventory persistence

`ResourceInventoryStore.RecordAsync(DbConnection, ResourceInventoryInput, CancellationToken)`
ports `wlre/services/world/resource_database.py:record_inventory` to the existing six-table
SQLite format. The closed, exclusively owned connection is supplied by the caller. The method
opens and disposes it; it does not select a filename, acquire credentials, register a provider,
access a user database, or install a runtime. Core uses only `System.Data.Common`. The test-only
Microsoft.Data.Sqlite package already used by the read-only snapshot reader supplies actual
temporary SQLite tests, with pooling disabled so Windows can remove owned temporary files.

## Source mapping and ordering

* Lines 13–30: select `tables/…*.bytes` members in supplied order, take their POSIX basename,
  reject duplicate basenames/invalid data, retain empty bytes, and optionally require the
  supplied `ManifestIdentity.Key`. Its existing canonical JSON/key semantics are unchanged.
  A missing identity is allowed; arbitrary bounded catalog keys and `.bytes` are accepted.
* Lines 31–67: create the source's six tables when missing, allow only the source's
  `sync_state.previous_id INTEGER` evolution, insert/select the catalog version, check the
  exact stored identity string, compute active/previous/parent descriptors, then persist raw
  bytes with same-version digest collision rejection. Omitted tables are not deleted.
* Lines 68–197: process items, Smith, Talk, Text, Scenes, Eve NPC and Eve interactions in that
  order using existing binary parsers. Each current parse occurs before prior-byte access.
  Current and prior parse failures retain their distinct `parse_failed`/`unavailable` report
  meanings. A missing current source differs from a present empty source. Empty derived maps
  are treated as absent saved views, as in Python. Saved nonempty row collisions are fatal,
  never converted into parser failure. Raw and derived differences use Python scalar lexical
  ordering rather than numeric or UTF-16 ordering. Smith's nullable keys and read-only fields,
  ItemData's flat reviewed details, all Stage fields, and Eve source-specific projections are
  retained. Existing ItemData reviewed-version/SHA checks and Eve parser limits remain intact.
* The returned report includes all source fields, including `smith_legacy_comparison: null`.
  Its immutable result and input copies cannot be modified through retained caller aliases.

`active_id` is a **database inventory selection**, not gameplay activation or `onActive`.
The caller's key, identity and hashes do not prove official provenance. Even a committed
receipt always has false provenance, runtime admission, AssetsReady and CanSendPackets flags.
No `AccountSession`, Android host, production transport, admission or runtime installation is
changed. `read_catalog_tables`, official fresh-source stability, static 1275 admission/count
checks, and production integration remain separate work. The existing database matcher and
read-only reader remain separate non-authorizing observations.

## Transaction and provider contract

One explicit `BEGIN IMMEDIATE` covers schema checks/evolution and all raw/derived/state DML.
Only after every parse/report and integrity check succeeds does `COMMIT` run. A failure before
COMMIT attempts uncancelled ROLLBACK, then disposal; cleanup errors never mask the original
error. Unlike Python's implicit first-DML transaction, this also rolls back newly created
schema and its legacy-column evolution if later work fails. This is intentional hardening,
not a claim that Python originally made DDL transactional.

The internal exception-data keys `ResourceInventoryStore.WriteOutcome`, `.RollbackSucceeded`
and `.CleanupFailures` distinguish NotCommitted, Committed and Unknown. A COMMIT execution
exception is conservatively Unknown even when a rollback succeeds; success observed before
command/connection-disposal failure is Committed. No automatic retry occurs. Callers must
reobserve an uncertain outcome rather than assume rollback or repeat an import blindly.
Cancellation is checked before COMMIT starts; once it starts the operation resolves its
outcome using an uncancelled token. Late cancellation after confirmed COMMIT is not reported
as an ordinary cancelled/rolled-back operation. A receipt requires clean completion/disposal.
Commit acknowledgement is an observation of the configured provider, not a certification of
power-loss durability or provider honesty.

SQL is parameterized and uses only the source table names in `main`; temp/main triggers on
these tables, unknown schemas, extra indices, altered collations, foreign keys, views and
virtual tables are rejected without reset or unsupported migration. Unrelated tables and
`user_version` are untouched. The conservative schema check accepts the exact source DDL
(with whitespace/case normalization), not every semantically equivalent SQLite DDL spelling.
No trigger or provider callback is treated as trusted. SQLite-compatible transaction/SQL
semantics, exclusive ownership, and a correctly configured provider remain caller obligations.
Command timeout and cancellation responsiveness depend on that provider, not hard realtime.

SQL CASE projections bound text/blob values and reject wrong storage types before provider
materialization. Integer-affinity state columns are type-guarded because SQLite can otherwise
store arbitrary TEXT/BLOB values there. `GetValue` must return the bounded BLOB as `byte[]`,
which is copied before advancing the reader. `GetBytes`/`GetStream` are intentionally not used:
Microsoft.Data.Sqlite 10.0.14's origin-metadata streaming path crashes on CASE BLOB projections.
The real SQLite regressions retain that projection. Text parameters are encoded as bytes and
cast to TEXT using the observed UTF-8/UTF-16 database encoding, preserving embedded NULs.

## Explicit stricter limits and integrity checks

The Python inventory writer has no ingestion quotas. These are additional fail-closed Core
limits, not attributed to that function:

* At most 512 supplied members; 256 selected/stored tables per relevant version; 2,048 UTF-16
  units per selected logical member path; 120 Unicode scalars per basename, 128 per catalog
  key and derived key; valid Unicode only; optional canonical identity at most 4,096 characters.
* Each raw table at most 16 MiB, including empty bytes, and each selected/accumulated version at
  most 128 MiB. The 16 MiB bound is consistent with the separate Python `read_catalog_tables`;
  256/128 MiB are conservative envelopes informed by `resource_rebuilder`, not source inventory
  limits. The whole database can contain multiple versions; these are per-version limits.
* One derived JSON row at most 256 KiB ASCII, one view at most one million rows and 64 MiB
  canonical object JSON (including quoted keys/punctuation). The accumulated current version
  is capped at two million derived rows and 128 MiB of ASCII JSON value bytes. UTF-16 storage
  multiplies the physical text-byte allowance by two. The query-projected payload counter is bounded
  to 256 MiB, excluding CLR container/object and provider-internal overhead, with bounded
  cardinalities and at most 16 columns; metadata has smaller SQL caps.
* Matching recorded hashes are not enough: every inserted/reused current raw table and every
  prior raw table actually parsed is rehashed from actual stored bytes and type/length checked.
  Newly inserted/reused current bytes must also equal the owned input. Unused prior/omitted
  rows are not all loaded; this does not certify every historic database byte.
* Existing parser-specific fail-closed differences remain. In particular the Core Eve parser
  rejects duplicate scene IDs where Python can overwrite them. No synthetic fixture bypasses
  ItemData SHA pins or grants static/runtime admission.

## Evidence

`generate_inventory_vectors.py` executes the **unchanged** Python inventory function, its
actual parsers, and stdlib SQLite against wholly synthetic fixtures. `--check` deterministically
replays 134 scenarios / 234 calls and compares compressed and decoded bytes. The C# theory
loader uses scalar IDs and lazily loads the pinned payload; large raw quota cases are compact
repeat recipes rather than giant JSON payloads. CRLF-only normalized hashes pin Python source.

Three scenarios describe Python-only invalid object types (wrong identity class, string raw
bytes, Python bytearray). C# verifies that these inputs are excluded by the typed API, rather
than claiming a runtime invocation with a different value is Python parity. Of the remaining
scenarios, six explicitly record source acceptance versus stricter Core rejection: tampered
current/prior bytes, trigger/schema/index anomalies, and an oversized raw table. All ordinary
transcripts compare the full report and all six database tables after every call, including
fatal error message/category and stored state after rollback.

Additional actual-SQLite fault-injection tests cover pre/late failures, cancellation,
rollback/disposal failures, pre/post COMMIT exceptions and confirmed commit cleanup failures,
UTF-8/UTF-16 and NUL values, immutable byte aliases, unsafe schema/storage shapes and quotas.
These are temporary fixture databases only; no production database or network is involved.

The POSIX transcript cases explicitly cover literal backslashes, repeated forward slashes,
`.` components and resulting duplicate basenames. No platform filename API or payload-path
filesystem operation is used.

Final isolated Release verification: 312/312 persistence/projection tests, then
12,557/12,557 impacted `Resources|Catalogs|World.Eve` tests, zero build warnings/errors.
Commands use the existing writable .NET SDK/cache configuration, a process-only 3 GiB GC heap
cap, `--disable-build-servers -m:1 -p:UseSharedCompilation=false`; the impacted run uses
`--no-build --no-restore`. Independent source/security review found no remaining blocker after
bounded identifier/state projections were corrected. No Android host build or production
integration is claimed by these Core checks.
