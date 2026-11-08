# Stored-column validation before resource reads

The snapshot and bootstrap-baseline readers already rejected views and virtual tables. An
ordinary SQLite table can nevertheless contain generated columns. A virtual generated identity
or payload column can evaluate a schema expression while SQLite evaluates the existing type,
length or CASE projection, before managed payload limits take effect.

The shared `ResourceInventoryReadShape` guard now checks bounded `pragma_table_xinfo` projections
for every column the pipeline reads. Each required name must appear exactly once with a normal
nonnegative column ordinal and `hidden=0`. Virtual and stored generated columns are rejected
before active-identity joins or payload value queries. Stored generated columns are also outside
the supported ordinary-column contract, although their expressions need not execute on reads.

The snapshot reader validates four tables within its existing read transaction. This protects
fresh runtime readback and the public local inspector. The pre-write baseline validates the
identity/selector tables that exist before source acquisition; its supported absent/partial
legacy-schema behavior is preserved. Metadata checks and subsequent value reads share the same
transaction. All existing size, type, checksum, identity, duplicate-row and cleanup checks remain.

Only fixed owned identifiers enter metadata SQL. Each metadata result is bounded to the known
required column count plus one detection row, with three columns per row. Cancellation, malformed
projections, hidden flags and extra result sets cannot return a snapshot. Commands/readers and
read-scope cleanup retain their existing ownership rules.

## Scope

This is not complete schema compatibility, source provenance or a sandbox for arbitrary SQLite
files/native engine behavior. It does not establish hard limits on all native query work. Extra
unread columns are ignored; an unrelated generated column does not change the required stored
columns' read contract. Defaults, constraints, triggers, other tables and generated values outside
these projections are not newly validated. The writer's stricter schema checks remain separate.
No account, command permission, public API or UI is enabled by this change.

## Synthetic evidence

Tests replace every required column in ordinary real SQLite tables with a virtual or stored
generated column. Deterministic echo-probe functions count evaluations; required-column rejection
must occur with zero read-time probes and before any identity/payload SELECT. Separate cases cover
baseline columns, untouched database bytes, unread extra generated columns, metadata faults,
cancellation and complete cleanup. Public inspection and runtime refresh reject even generated
payloads that reproduce the original bytes/hashes. Bootstrap rejects generated baseline columns
before any source call. No official network or actual user database is accessed.

Verification: the focused Release selection passed 445/445 tests, covering runtime owner/bootstrap,
SQLite snapshot reads, the new shape checks, persistence and retained Python database-read parity.
An initial run exposed test-only probe registration before the native SQLite connection opened;
registering probes on the opened connection corrected setup, and the full selection then passed.
Independent source review found no blocking issue. This is synthetic/local evidence only.
