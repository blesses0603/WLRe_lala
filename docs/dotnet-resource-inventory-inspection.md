# Read-only inventory recovery inspection

`ResourceInventoryInspector.InspectAsync(absoluteDataRoot, cancellationToken)` examines the
fixed local resource inventory without downloading sources or changing account/runtime state.
It is useful after a Committed/Unknown write result, before deciding on another explicit
source-verified preparation. It never retries a write, repairs a schema, deletes a file or
retroactively changes an earlier storage outcome.

The inspector opens `official_sync/derived_catalogs/resource_inventory.sqlite3` with concrete
Microsoft.Data.Sqlite ReadOnly mode, private cache, no pooling and the existing command timeout.
It reuses the bounded reader's single explicit read transaction and waits for all read/rollback/
connection cleanup before hashing the detached snapshot. Missing files/directories are not
created. It performs no inventory DML or schema migration; this is not a claim about SQLite's
native auxiliary-file behavior in every journal configuration. Path containment is lexical,
not protection against hostile symlinks or filesystem replacement.

## Local checks and limits

- Four required ordinary main-database tables and unambiguous active/required-row projections.
- Canonical schema-1 identity JSON with exactly two ordered package entries, supported version
  syntax, bounded lowercase digest/CRC text, no duplicate/extra keys or alternate serialization.
- SHA256 of the actual identity representation equals its stored catalog key.
- Exactly the ten required tables are selected; every actual BLOB hashes to its recorded SHA256.
- A 16 MiB per-table limit and 32 MiB aggregate inspection budget. The reader stops before
  detaching an oversized snapshot. It may temporarily hold the retained prefix plus one bounded
  table while detecting the excess; native/provider buffers are outside managed payload quotas.
  These are not hard query-time deadlines or limits on total database size/native query work.

The shared reader's existing default aggregate limit remains 160 MiB for existing callers.
Its new optional budget is validated within its ownership scope, so even invalid budgets dispose
the transferred connection. No parser limit, admission check or original test coverage is relaxed.

## Interpreting the result

The sanitized result contains status and, only on success, the local catalog identity,
DataVersion/ExeVersion, required-table count and total raw bytes. It does not expose paths,
exceptions, arbitrary JSON or table contents. Missing means no inventory was found at the
initial filesystem check. Invalid means the bounded local checks failed. Unavailable covers
I/O, permissions, busy/other SQLite errors or cleanup failure. Cancellation is propagated.

SelfConsistent is deliberately **not** official provenance, current-source equality, decoded
catalog usability, complete schema compatibility, runtime admission or permission to send.
Someone who replaces both a BLOB and its recorded hash can retain local self-consistency;
fresh source/database matching still rejects that substitution. Optional tables, parsed derived
rows, other versions and full-database integrity are outside this inspection's scope.

The result is a point-in-time read observation. Another owner/process may commit afterward.
A current self-consistent inventory does not prove which earlier uncertain COMMIT ran or that
its acknowledgment was delivered. It supplies evidence for an explicit recovery decision, not
authority for automatic retry/rollback or packet access. All admission/command flags remain false.

## Offline tests

Tests use synthetic bundle bootstrap into real isolated SQLite files. They cover unchanged
readback/no source calls, missing and malformed files, pre-cancellation, raw/hash mismatch,
missing rows, identity mismatch/duplicates/noncanonical serialization, local forgery without
provenance, both uncertain-COMMIT branches, aggregate quotas and connection cleanup on invalid
budgets. These do not inspect a real user's database or contact official servers.

Verification: the final owner/bootstrap/snapshot-reader focused selection passed **152/152**
Release tests with no failures or skips using the unchanged full test project, a process-only
2.5 GiB GC heap cap, one reported processor and non-shared single-node compilation. Independent
review found one cleanup-status precedence mismatch, now fixed with a regression: attached
cleanup failure takes precedence over Invalid/Missing, while cancellation still propagates.
The final review found no blocker. Full combined-head/platform checks remain separate.
