# Read-only transactional resource snapshots

`RuntimeDatabaseSnapshotReader.ReadAsync(DbConnection, CancellationToken)` is an
internal, provider-independent Core seam. It takes ownership of a **closed,
exclusively supplied, read-only SQLite-compatible connection**, opens it, issues
an explicit deferred `BEGIN`, reads the active identity and all ten required raw
resource rows in that transaction, copies them into an owned snapshot, then issues
`ROLLBACK` and disposes the connection. It never commits, creates or migrates a
schema, writes resource data, locates files, discovers a provider, or opens a user
database itself. Test databases are newly created, synthetic, temporary files.

## Provider contract and trust boundary

Generic `DbConnection` has no API that proves filesystem read-only mode, honest
SQLite execution, connection exclusivity or isolation. The supplying adapter must
configure a reputable SQLite provider for read-only access and give this method
exclusive connection ownership. No fallback interprets an arbitrary provider as
SQLite. Tests use the already referenced official `Microsoft.Data.Sqlite` 10.0.14
with `Mode=ReadOnly` and pooling disabled. The reader itself remains provider-neutral.
The later `ResourceRuntimeOwner` now adds a concrete Microsoft.Data.Sqlite `[10.0.14]`
dependency to Core, including transitive native SQLite assets. Filesystem/symlink
rules remain a separate adapter responsibility.

`CompletedSingleReadTransaction` means the reader completed its commands and
cleanup under that provider contract. It is not a durable database certificate or
a security capability. No observation is returned if reading, cancellation,
rollback or disposal fails. `HasVerifiedProvenance`, `RuntimeAdmitted`,
`AssetsReady` and `CanSendPackets` always remain false. The returned
`OwnedRuntimeDatabaseSnapshot` can be passed to the existing structural matcher;
its supplied identity and hashes remain non-authoritative and its
`ProvesDatabaseTransaction` flag remains false. Neither API installs state or
confirms AccountSession resources.

Explicit `BEGIN` preserves the Python deferred read transaction rather than
using `DbConnection.BeginTransaction`, whose SQLite provider default may issue
`BEGIN IMMEDIATE`. The transaction also reads `PRAGMA main.encoding` and supports UTF-8, UTF-16le
and UTF-16be, preserving the database encoding when validating text byte lengths.
Every command requests a five-second timeout, but timeout,
async execution and cancellation latency remain provider-dependent. They are not
hard real-time guarantees. Cleanup uses an uncancelled token. If a failed BEGIN
may have executed, rollback is still attempted. A primary failure keeps its exact
exception type, instance and stack; secondary reader, command, rollback or
connection cleanup failures are retained as an immutable list in its exception
Data. Successful reads with failed cleanup throw instead of returning a snapshot.

## Bounds and malformed-schema handling

The selected source schema is the four ordinary tables `sync_state`, `versions`,
`version_identities` and `resources` created by Python `record_inventory`.
All queries explicitly select the main database. A bounded `main.sqlite_schema`
projection rejects missing tables, views, virtual tables and duplicate names;
ordinary tables require a positive root page. No schema is repaired. Additional
unrelated tables are ignored. Missing/renamed columns fail through the provider.

The active join follows the Python relationship exactly. At most two joined rows
are requested, and more than one is rejected. Each exact `<source>.bytes` lookup
is parameterized with the same active Int64 ID and also limited to two rows;
duplicates reject rather than picking an arbitrary first row. SQLite storage types
must be integer/text/blob as appropriate. No coercion of text or integers into
blob bytes is allowed. Text is guarded by SQLite byte lengths, including embedded
NUL, and by managed character lengths; JSON is bounded to 4096 characters.
Identity hashing and parsed identity equality remain the structural matcher's job.

`CASE` projections prevent an oversized blob or text value from entering the
managed projection. Nonempty blobs are limited to 16 MiB each, type/length checked
again as a strictly typed `byte[]` returned by `GetValue`, and copied into owned
storage in chunks of at most 64 KiB. Non-byte-array values, nulls, length mismatch
and extra result sets reject. The provider materializes one bounded value; this
is not a provider-streaming contract. Only ten tables
are read: at most 160 MiB of temporary bytes and 160 MiB of detached snapshot bytes
while capture completes, plus at most 16 MiB for the current bounded provider
array. Dead temporary allocations awaiting GC, provider-internal read-ahead/cache
allocations, native buffers and caller connection internals are outside these retained-payload bounds. Returned snapshots own their bytes and do
not retain the connection, reader, command or temporary byte arrays.

This bounded reader is deliberately stricter than Python `fetchone` for damaged
schemas, duplicates, views, storage classes and some malformed identity values.
It is not a claim of identical SQL or identical short-circuit query order:
reading the bounded snapshot happens before the independent structural matcher.
Retained source outcomes and stricter capture expectations are labeled separately.

### Provider regression

The real `CASE`-derived blob projection is a regression fixture. With
Microsoft.Data.Sqlite 10.0.14, the first null-buffer `GetBytes` length probe caused
a native SIGSEGV after all preceding queries/type checks succeeded. The package's
exact source shows `GetBytes` delegates to `GetStream`, whose origin-metadata path
can encounter expression columns without database/table/column origins. Switching
to `GetStream` or changing `SequentialAccess` would not avoid that path.

The reader instead uses `GetValue` as its single primary contract, after unchanged
SQL pre-materialization bounds. It never tries streaming APIs or retries another
API on failure. Scripted test readers explicitly throw if `GetBytes` or `GetStream`
is called. Provider arrays are copied before another query can reuse/mutate them;
late cancellation at materialization cannot publish a result. This does not change
the data, size, duplicate, transaction or cleanup contracts.

Provider source at its package-pinned repository commit:
[SqliteDataRecord](https://github.com/dotnet/dotnet/blob/0427b9abbead3fa64c6655eb4290c537397131fa/src/efcore/src/Microsoft.Data.Sqlite.Core/SqliteDataRecord.cs#L258-L393) and
[SqliteValueReader](https://github.com/dotnet/dotnet/blob/0427b9abbead3fa64c6655eb4290c537397131fa/src/efcore/src/Microsoft.Data.Sqlite.Core/SqliteValueReader.cs#L398-L426).

## Evidence and platform scope

The retained generator executes the complete unchanged Python
`database_matches_runtime` AST against real temporary stdlib SQLite files. Its 52
cases retain separate Python-match, strict-reader-capture and reader-match
expectations, including valid UTF-16le/be databases and ten intentional stricter
rejections. Source hashes normalize CRLF only. The compact compressed fixture
retains compact operation/blob recipes, not expanded maximum blobs; its lazy
loader discovers only scalar case IDs. Reproduce with
`python dotnet/Lala.Core.Tests/Resources/DatabaseRead/generate_database_read_vectors.py --check`.

The real-SQLite tests check read-only enforcement and unchanged database bytes,
correct command/parameter order, complete disposal, and a WAL writer changing the
active generation and old payloads between reads. The first attempt retains one
coherent old snapshot; a later attempt sees the new generation. Scripted provider
faults cover cancellation, uncertain BEGIN, late read failures, malformed types
and materialized blob types/lengths, rollback failure, and preservation of primary errors when all
cleanup stages also fail. Independent source/security review is required.

Core continues targeting `net10.0`; this reader uses cross-platform System.Data.Common
and other BCL APIs, with no Windows-only database adapters, provider reflection,
P/Invoke or host API changes. The separate owner brings concrete SQLite/native assets
into Core consumers; fresh Android restore, ABI packaging and native-load/device
verification are required rather than implied by reader tests. The owner composes
resource-only admission separately; production host registration, live-origin validation,
gameplay compatibility and runtime installation are not established by this reader.
