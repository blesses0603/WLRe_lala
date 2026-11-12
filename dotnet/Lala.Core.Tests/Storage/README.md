# Ark question evidence storage: offline Core boundary

Source: retained `wlre/storage/ark_questions.py`. `Lala.Core.Storage.ArkQuestionStore`
implements observation, reviewed candidate recording, durable once-only claims, explicit
candidate-attempt recording, server-confirmation evidence, rejection, and permanent
conflict quarantine. It does not implement a candidate solver or send any answer.

## Host contract and ownership

- Construct with a caller-supplied `Func<DbConnection>` returning a **new closed SQLite
  connection per operation**. The store opens and disposes it. There is no path lookup,
  directory creation, default user database, native SQLite initialization, provider reference,
  session wiring, or background work in Core. SQLite SQL/Int64 storage values are required;
  this is not a generic relational-database adapter. Operations perform synchronous I/O;
  production hosts must schedule them away from UI threads and own cancellation/lifecycle.
- Inputs reuse `Social.Ark.ArkCatalogToken` and `ArkQuestionSnapshot`. A positive
  `BigInteger` role preserves Python's non-wire role range, including values above uint.
  Python's default 4,300-decimal-digit serialization bound is enforced before hashing.
- Existing receive `ArkQuestionMemoryIntent` values remain **unexecuted**. This boundary
  does not validate a live session/generation, catalog provenance, pending event, or server
  receipt. A future host adapter must revalidate the entire current identity and explicit
  server evidence before invoking it, and must not mistake `Confirm` for server verification.
- Every operation recomputes the catalog/role/fingerprint key from all exact question text,
  option IDs and their corresponding labels. Only option ordering is ignored. Caller-carried
  `KnownAnswer`, selection, candidate provenance, and award fields cannot create authority.
  Constructors/results and content hashes themselves do not authorize game actions.

## Storage and failure contract

- All operations, including observation, use `BEGIN IMMEDIATE` before schema/evidence
  reads, then commit only after the complete operation succeeds. Competing stores are
  serialized by SQLite, not by a process-local lock. No automatic retries or DB resets.
- Schema versions 0/1/2 are supported, with the source's additive tables and migration to 2.
  Compatible existing Python databases are supported. Unknown versions, wrong/extra or
  hidden columns, wrong defaults/types/primary-key collation, extra indexes, triggers,
  views in place of tables, and foreign keys fail closed. Trigger-owner detection respects
  SQLite identifier case-insensitivity, including uppercase ON table spellings. Additional restrictive CHECK
  constraints may produce a propagated SQLite exception and full rollback.
- Before use, selected persisted evidence is checked for integer/flag/provenance validity,
  allowed option membership, state consistency, and a complete canonical payload match.
  A reviewed candidate and a different valid-option attempt are inconsistent unless already
  quarantined; confirmation must not silently erase that contradiction. All catalog/role/
  fingerprint predicates explicitly use BINARY comparison even when a compatible table's
  column default collation differs from its BINARY primary-key index. Insert conflicts use
  that validated BINARY key, so reads, updates, deletes and once-only claims share exact identity.
  Malformed or contradictory persisted metadata cannot become a confirmed answer. Unlike
  the Python source's permissive schema/row reads, corrupt evidence raises
  `InvalidDataException`; it is not repaired, overwritten, or silently quarantined.
- Candidate evidence always leaves observation unknown until explicit matching confirmation.
  Contradictions preserve the first candidate/attempt and permanently clear confirmed
  authority. Metadata refresh cannot lift quarantine. Rejection of a candidate clears its
  pending claim and marks it rejected; a noncandidate rejection affects only the matching
  confirmed answer. An unregistered manual attempt does not create a candidate. As in
  Python, server confirmation resolves an unregistered pending attempt even if the attempt
  answer differs; an attempt alone is not competing reviewed evidence.
- Invalid caller input raises `ArgumentException` before opening the connection. Provider
  and I/O exceptions propagate. Cancellation is checked before opening, at SQL boundaries,
  during bounded result reads, and before commit; cancellation/failed statements roll back.
  Cancellation is cooperative, not guaranteed to interrupt a provider's in-flight call.
  SQLite busy timeout is 250 ms and each provider command has a 1-second timeout. The
  official Microsoft provider can retry up to that whole-second timeout, a documented
  difference from Python's 250-ms connect timeout. Microsoft.Data.Sqlite exposes whole-second
  command timeouts, not a 250-ms retry limit; zero would mean unlimited and is not used.
  The factory is the explicit provider boundary; a provider that honors the SQLite busy
  pragma without its own retry can preserve 250 ms. There is no unbounded lock retry.
- A commit/rollback failure propagates; a rollback failure is attached to the original
  exception's Data under `ArkQuestionRollbackError`. No successful result is synthesized
  after an uncertain commit. The host must not blindly retry a consequential operation.
- Text/labels use Python Unicode-scalar length limits (32,768 each), reject unpaired
  surrogates, and preserve exact normalization/control characters for identity. Provenance
  is bounded to 1,024 scalars. Persisted payload/provenance retrieval and row counts are
  bounded before use. Custom validation errors and identity ToString do not print question content, catalog hashes, or role identities; provider exception details remain provider-defined.

## Differential and contract evidence

Run the deterministic generator from the repository root:

```sh
PYTHONPATH=/tmp/daily-assistant-deps python dotnet/Lala.Core.Tests/Storage/generate_ark_question_storage_vectors.py
```

It executes the real retained Python store on synthetic temporary SQLite databases and
produces 104 identity vectors, 149 operation scenarios (1,402 operations), and actual
Python-created v0/v1/v2 database images. SHA-256 of the source and exact compressed/decoded
fixture bytes are retained. The 46,535-byte gzip uses the shared deterministic helper and
an explicit culture-independent embedded resource name; no fixture strings use the C#
user-string heap. Tests compare every operation result and complete persisted tables,
including source provenance, flags, pending claims, payloads and fixed timestamps. Boundary
identity vectors also exercise all five strings at 32,768 supplementary code points and
worst-case JSON escaping, with 1-digit and 4,300-digit roles.

Contract tests additionally cover Unicode/role boundaries, malformed input before open,
corrupt files and stored payloads, identity tampering, rejected/invalid evidence, schema
migrations, failed-second-write rollback, cancellation and exceptions after a first write,
lock timeout, competing contradictory confirmations/candidates, cross-connection once-only
claims, and preservation of quarantine and first provenance.

Test-only dependencies, restored from official NuGet: `Microsoft.Data.Sqlite` and
`Microsoft.Data.Sqlite.Core` **10.0.14**; `SQLitePCLRaw.bundle_e_sqlite3`, `core`,
`lib.e_sqlite3`, and `provider.e_sqlite3` **2.1.13**. Core remains dependency-free.

## Remaining gates

This is an offline storage implementation, not completed Ark automation. Selecting and
initializing production SQLite providers on Windows/macOS/Android, choosing private
user-data paths, permissions/backups/corruption handling, integrating current-session
identity and generation checks, executing receive intents, candidate matching/solver work,
command dispatch and answer sending, lifecycle wiring, real-device/runtime concurrency,
and official-resource/server acceptance all remain separate and unverified. No actual
user database, credentials, live network/game, Android or UI was used by these tests.

## Initial verification (before independent-review follow-up)

- Core Release full suite: **24,633 passed**, zero failures/skips, on base `654118a`
  plus this storage increment.
- Focused `FullyQualifiedName~Storage`: **362 passed**, comprising **326 new storage
  tests** (256 parity/database-image cases + 70 contracts) and 36 existing matching cases.
- Retained Python `tests.test_ark_question_store`: **36 passed**.
- Regeneration produced byte-identical gzip twice; decoded fixture is 8,286,202 bytes,
  below the shared helper's 32-MiB bound. `git diff --check` passes.
- Restore used only `https://api.nuget.org/v3/index.json`; no production dependency added.
  An initial compile rejected two xUnit Assert.Single patterns; these were corrected,
  then both successful Release test runs above completed with warnings treated as errors.

These are Linux offline checks. They do not satisfy the remaining host/runtime gates above.

## Independent-review follow-up

Closed two independently reproduced blockers: contradictory reviewed-candidate/valid-option
attempt rows now fail before confirmation can clear them, and identity predicates explicitly
use BINARY comparison rather than inheriting column collation. Added a third adjacent schema
hardening found during follow-up: uppercase trigger-owner spellings cannot bypass rejection.

Focused Release `FullyQualifiedName~Storage`: **371 passed**, zero failures/skips, including
**335 storage tests** (256 parity/database-image cases and 79 contracts) plus 36 existing
matching cases. Nine added cases cover all operations on corrupt valid-option attempts,
quarantined versus unregistered-attempt semantics, catalog/role/fingerprint read-and-write
isolation with NOCASE columns/BINARY primary keys, and uppercase trigger owners on each of
the three evidence tables. The complete Core suite is left to the parent integration run;
the earlier 24,633-test full result above predates this follow-up. No fixture or dependencies
changed. `git diff --check` passes.
