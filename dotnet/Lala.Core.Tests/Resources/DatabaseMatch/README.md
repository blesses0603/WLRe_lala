# Supplied database snapshot structural matching

`RuntimeDatabaseStructuralMatcher` is internal and pure. It checks one detached,
owned set of supplied database observations against a supplied `ManifestIdentity`
and expected digest map. A successful match means only that these values agree.
It does not establish where either side came from or certify that the observations
were read in one actual database transaction. `HasVerifiedProvenance`,
`ProvesDatabaseTransaction`, `RuntimeAdmitted`, `AssetsReady`, and `CanSendPackets`
remain false on every result. No admission capability is produced or consumed.

## Supported source sequence

The retained oracle executes the unchanged `try` AST from
`wlre/services/world/resource_database.py:321–344`, inside
`database_matches_runtime`. The C# matching order is:

1. Require precisely the ten required unsuffixed expected source names. Copy their
   supplied iteration order, bounded to ten entries, before inspecting identity.
2. Require an active record with exactly `ManifestIdentity.Key`, bounded stored
   identity JSON, ASCII encodability, the SHA-256 of the original stored ASCII
   text equal to that key, then parsed JSON equality with the manifest identity.
   Do not substitute `OfficialCatalogObservation.CatalogKey` or reserialize the
   stored text before hashing. `ManifestIdentity.CanonicalJson` exposes the same
   internal string already used by the existing key derivation; its key algorithm
   is unchanged.
3. In expected-map order, require each exact `<name>.bytes` row at the active
   version, its recorded digest equal to the expected value, a non-null blob with
   `0 < length <= 16 MiB`, and a freshly computed SHA-256 of its owned bytes equal
   to that expected value. Report only the examined source names, never payloads.
   Empty bytes, missing rows and null blobs remain distinguishable in the input.

The snapshot input represents already selected query observations, not a database
reader. Each supplied row carries its exact name and version. Both are checked,
so a case-insensitive input map cannot promote an inexact resource name. Only the
exact ten active-version slots are copied. Extra names and stale versions are
ignored without enumeration or copying. Each valid blob is copied from its exact
`ReadOnlyMemory` slice; the owned result retains no caller byte array or row map.
Oversized blob/string backing data is not retained. The maximum retained table
payload is ten times 16 MiB, or 160 MiB. Expected-map enumeration is capped at
an eleventh entry even if a custom dictionary lies about its count. Cancellation
throws before publication, including cancellation during capture and map copying.

Typed inputs intentionally do not model arbitrary Python object types or SQLite
storage classes. A future reader must reject a non-BLOB SQLite value rather than
coerce it to bytes. Source filesystem preflight, read-only SQLite open, `BEGIN`,
join behavior, transaction isolation and SQLite exception handling are not
implemented here. Zero and negative version IDs are not invented rejection rules.
The row map is a supplied query projection, not a whole database with duplicate
primary keys. Separate capture does not imply physical database coherence, nor
does it protect against concurrent mutation while the caller supplies bytes;
mutations after capture cannot alter the owned snapshot.

## Retained evidence and tests

Run `python dotnet/Lala.Core.Tests/Resources/DatabaseMatch/generate_database_match_vectors.py --check`.
The generator compiles the unchanged actual Python AST, derives the real Python
`OfficialCatalogIdentity` from tiny synthetic manifest inputs, and records exact
source SQL query order through an inert scripted connection. It performs no
SQLite I/O, game filesystem probing or network requests. Source hashes normalize
CRLF to LF only; bare CR is preserved.

The 128 retained cases cover exact expected sets, expected ordering, active and
identity mismatches, ASCII/length/hash/JSON failures, missing/null/tampered/stale
rows, recorded and expected hashes, optional/extra rows, and payload boundaries
at 16 MiB minus one, exactly 16 MiB and one byte over. Fifteen cases match; none
establish official authority. Boundary payloads use compact repeat recipes that
are instantiated only when their scalar-ID test runs. xUnit discovery does not
inflate the lazy compressed fixture. Fixture evidence pins the generator, source,
compressed and decoded bytes. C# also pins the retained source files and checks
outcomes plus the exact prefix of resource checks from the actual Python trace.

No custom identity key override exists. Because the typed identity key is derived
from the genuine canonical JSON, malformed or differently formatted JSON fails
the preceding hash check. The parsed equality check is retained but is not falsely
claimed to have an independently reachable negative case without a SHA collision.

Additional C# tests cover metadata/manifest key separation, exact slice ownership,
mutation and alias independence, immutable results, late byte tampering,
case-sensitive names through a case-insensitive map, no enumeration of optional
rows, no copying of stale/oversized payloads, allocation bounds, cancellation,
missing inputs and dishonest expected-map counts.

## Remaining gates

This is not production database wiring. Official transport/provenance, fresh
source re-observation, a real coherent database transaction, schema-aware table
loading, static-1275 admission/count gates, runtime installation and AccountSession
resource confirmation remain separate and unavailable through this API. Existing
reviewed SHA pins and other resource gates are unchanged. No SQLite dependency,
network, cache/publication, credentials, Android or session API is added to Core.
