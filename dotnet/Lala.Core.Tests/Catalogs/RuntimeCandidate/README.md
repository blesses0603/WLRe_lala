# Owned ten-table offline runtime candidate

`OfflineRuntimeCandidateDecoder.Decode` composes the dynamic branch's structural table
construction from supplied bytes into one immutable, non-authorizing result:

1. Snapshot all ten required sources in extraction order: Eve, ItemData_C, TalkData_C,
   TextData_C, SmithData_C, ScenesData_C, AdventureData_C, AdventureLvData_C,
   NpcData_C, NpcCareerData_C. Missing and empty inputs differ. Each source is bounded
   at 16 MiB; unknown extra keys, including claimed provenance, are ignored.
2. Parse Eve NPC/interactions using the existing full v115 parser and its original
   combined-then-per-feature failure fallback. Parse ItemData with its existing public
   version policy and fixed 1296 SHA-256. Retain item insertion order. For shop forms
   2/3, kind-3 offers require database kind 2 and a matching ItemData ID.
3. Parse Talk/Text with existing decoders. Parse reviewed Smith 33/35 rows, validate
   every product and material against those same owned ItemData rows, reject zero
   material counts, and preserve exact OpenUsed values. All recipe identities stay
   in source order. Duplicate products are excluded only from the product lookup,
   including conditional recipes; they are never discarded or guessed.
4. Parse scenes, then project Eve door/event/convey data with the separate source-faithful
   door parser. Empty scene/talk/text checks occur after door projection. Source-relative
   stages and failures remain ordered. Event-portal reconciliation, route conflicts and coverage are not included.
5. Parse expedition tasks/levels, then career/NPC data, then strict runtime names with
   the existing decoders/binder. Bind scene names with Python whitespace/codepoint
   semantics, skipping invalid/missing labels rather than inventing fallback names.

There is no source rule requiring Eve NPC IDs to exist in the expedition NPC table.
The candidate therefore does not invent that join. Convey destination observations do
not validate a route or authorize travel. Shared parser-owned collections are immutable;
no caller bytes or dictionaries are retained. Cancellation and every error prevent a
result from being returned. Previously returned candidates are never mutated.

## Deliberately missing gates

This is the **dynamic structural branch**, not `load_verified_bundle_runtime`, source
verification, or static 1275 admission. It does not implement the static 1275 Eve/adventure
hashes, audited counts or recipe count gate, and has no API claiming that it does. The
standalone `EveDoorParser.ParsePinned1275` separately requires its original fixed SHA.
No custom-hash or public synthetic-layout bypass was added. Positive synthetic candidate
cases use the actual legacy ItemData public policy; 1296 synthetic inputs must reject.

The candidate's content hashes describe owned bytes only. Caller maps and package labels
cannot establish official provenance. Fresh official source/manifest stability,
verified extraction-to-table binding, database-byte admission and runtime installation
remain separate missing connections. This class does not change session APIs, issue an
admission token, set `IsCompleteState`, confirm AccountSession resources or enable
AssetsReady/CanSendPackets. `RequiredTablesStructurallyComplete` means only this local
construction returned successfully, even if the candidate is irrelevant to the server.

SkillData, portal metadata, images, daily/guild/Ark and all other optional catalogs remain
explicitly unavailable. Nothing silently promotes the ten-table result into those
features. No file cache, publication, live network, credentials, UI or Android work is
performed here.

## Retained evidence

`generate_runtime_candidate_vectors.py` runs the exact AST statements for the required
construction stages of the retained Python runtime, including its real dynamic recipe
function, shop checks, nonempty checks and strict expedition-name block. It deliberately
excludes verified-context extraction, cache/storage, optional features and activation.
It executes a local in-memory `stored` callback, never a database. The expected projection
covers new relationships, ordering, hashes and meaningful linked values; the existing
parser test families cover every raw field. Door tests separately retain full projected
rows and diagnostic observations.

Synthetic ten-table success includes an Eve NPC, shop, door, unsigned condition, signed
result and convey; duplicate product recipes with distinct identities; named scene and
expedition task, level, career and NPC. The tests also cover duplicate/material behavior,
OpenUsed 0/255 without invented authorization, form/kind/database shop matrix, names and
Unicode boundaries, error precedence including late door failures, missing/empty sources,
ownership, immutability, byte ceilings, cancellation and mandatory reviewed pin rejection.

Fixtures have deterministic gzip and decoded SHA-256 checks, CRLF-only source pins, scalar
case IDs, lazy resource loading and failure-only detailed messages. No real game bytes,
local game paths or maximum-count JSON are retained. Constructors are imported as AST
function definitions only, so this generator never triggers the older generators' large
fixture loops.

Regenerate from repository root:

```sh
python dotnet/Lala.Core.Tests/Catalogs/RuntimeCandidate/generate_runtime_candidate_vectors.py
```

Focused tests (when compiler slot is available):

```sh
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter 'FullyQualifiedName~RuntimeCandidate|FullyQualifiedName~EveDoor'
```

Verification: **1,102 focused Release tests passed** (166 candidate tests and 936 door
tests), followed by **11,247 impacted Catalogs + World.Eve tests passed**, no skips.
Both used the existing process-only 3 GiB GC heap cap and writable SDK/cache paths;
no production setting or package policy changed. Independent source/security review
approved the final changes. All three generators regenerated byte-identical artifacts;
53 existing related Python unittest tests also passed with the repository test path.
The initial .NET restore needed writable XDG paths; an initial test-only reference-identity
assertion was corrected to compare complete detached diagnostic values before the passing
rerun. These are focused/impacted receipts, not a full-suite, platform or official-server pass.
