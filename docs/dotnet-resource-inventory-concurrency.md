# Optimistic active-inventory write precondition

Previously each ResourceRuntimeOwner serialized its own preparation, but independently owned
preparations could overlap: an older source preparation could obtain the SQLite write lock
later and replace a newer owner's active selector. Final source reobservation might prevent
runtime admission afterward, but would not undo that committed selector change.

Bootstrap now captures a local active-inventory baseline **before source acquisition**. An
absent file/directory yields an empty baseline without creating storage. Existing inventory is
opened ReadOnly in one deferred read transaction. The baseline retains the active row ID and
bounded exact stored catalog-key/identity bytes (hex encoded), not provider-decoded approximations.
Read commands, rollback and connection cleanup finish before any source request or writer opens.
Unreadable, ambiguous, oversized or malformed active state does not become an empty baseline.

Inside the existing `BEGIN IMMEDIATE` writer transaction, after safe schema validation/additive
creation but before inventory INSERT/UPDATE operations, the store rereads and compares that
baseline. A different active selector or identity rejects the write. SQLite's writer lock keeps
another ordinary writer from changing the compared state between the check and this commit.
Any additive DDL remains in that transaction and is rolled back on rejection.

This applies to the owned production bootstrap path. The bounded generic inventory primitive's
optional precondition defaults to absent, preserving its prior source-parity contract. The
public facade supplies no caller-selected baseline or bypass. Read-only Refresh is unchanged.

## Outcomes and supported legacy state

A rejected writer reports NotCommitted after confirmed rollback, with no commit admission or
runtime publication. Rollback/cleanup uncertainty still preserves Unknown where the existing
store's outcome rules require it. No retry, compensating write or deletion occurs. A caller may
choose a fresh explicit preparation; it must not treat Unknown as permission to retry blindly.
Even a concurrent writer selecting the same intended version can conservatively cause rejection
when it changed the baseline captured by this attempt.

Supported additive schema creation remains available: no selector is empty state, an empty
selector can acquire its missing versions table, and an absent identity table/row represents no
identity yet. The store still validates the resulting full schema before any inventory DML.
An existing active selector without a valid referenced version is malformed, not empty.
Unrelated tables remain untouched. Existing raw-byte, immutable-row, source-version and final
readback/admission checks are unchanged.

## Scope and limits

This is compare-and-swap of the observed active selector/identity, not a global monotonic revision,
complete database fingerprint, cross-process mutex, or wall-clock ordering of requests. A change
away and back to exactly the same captured state is not detected. Other-version rows, derived
rows and parent metadata are outside this baseline; their existing writer checks still apply.
Conflicting supplied raw bytes and nonempty derived views are still rejected. An entirely
missing derived view may still be regenerated under the existing store contract; no complete
row-history/deletion-preservation claim is introduced.
It does not defend against hostile filesystem replacement/symlinks or dishonest providers.
The initial baseline is local concurrency state only, never source provenance or packet authority.

Tests deterministically pause one owner after baseline capture, let another owner commit, then
resume the older owner. They cover initially absent/existing storage, newer/same source versions,
rollback uncertainty, no stale INSERT/COMMIT, unchanged winning database bytes, baseline cleanup
and cancellation before source acquisition, bounded metadata, malformed active state and supported
partial legacy schemas, UTF-8/UTF-16 databases and exact malformed UTF-8 identity-byte changes.
All sources/databases are synthetic and isolated; no official server or
actual user inventory is accessed. Real multi-process/device acceptance remains separate.

Verification: final owner/bootstrap/snapshot-reader/inventory-persistence focused selection
passed **352/352** Release tests with no failures/skips, using a process-only 2.5 GiB GC heap
cap and single-processor/non-shared compilation. The initial selection passed 351 cases and
hit one existing disconnect fixture's reset-versus-EOF race; that four-case group then passed
4/4, followed by the complete 352-case rerun. No database assertion failed. The connection
workstream owns the separate fixture correction. Independent read-only review found no blocker;
full combined-head and real multi-process/platform checks remain separate.
