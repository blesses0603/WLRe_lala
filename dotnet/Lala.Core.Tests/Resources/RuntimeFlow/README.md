# Owned bundle-to-runtime fixtures

These small, genuine UnityFS fixtures join the bounded bundle/TextAsset decoder to
the ten-table runtime candidate using original synthetic bytes. They are not game
extraction evidence, official provenance, resource readiness, session admission, or
an Android call site. No game installation, user data, class database, private local
paths, network source, or credentials are included.

## Source and real writers

`generate_runtime_flow_fixtures.py` reads case `0`, `all-ten-duplicate-products`,
directly from the retained `Catalogs/RuntimeCandidate` gzip fixture. Its complete
SHA256 is pinned before decompression; every base64 payload is validated against
the retained expected SHA256. The raw fixture generator is **not** imported.

The main-guarded sibling `UnityTextAssets/generate_fixtures.py` supplies the reviewed
58-node AssetBundle and 9-node TextAsset trees. A new multi-object builder constructs
owned SerializedFiles, rewrites them with **UnityPy 1.25.4 SerializedFile.save**, then
constructs real UnityFS objects and retains the output of **BundleFile.save('lz4hc')**.
Compression uses the installed **lz4 4.4.5** package. Both writer round trips are
required to be byte-identical.

A fresh UnityPy reader validates every script's exact raw bytes with
`surrogateescape`, object names, object IDs, classes, type trees, container entries,
dependencies, and external metadata. Duplicate entries are inspected in the type
tree sequence, not a dictionary that could collapse duplicates. The external fixture
also checks pointer dereferencing against an explicitly assigned, already parsed
in-memory target. UnityPy's basename resolver is **not** evidence for Core's stricter
full-identity or allowlist policy, and is not allowed to probe files or the network.

Every retained bundle is UnityFS8 / SerializedFile22 / Unity2021.3.45f2, with LZ4HC
flag `0xc3` and the exact directory entry `CAB-runtime-flow`. Repeating that CAB name
is deliberate: different bundles are distinct `(bundle name, directory name)` file
identities.

## Cases

The exact paths are `Assets/ResourcesBuild/Data/<table>.bytes`; TextAsset names are
the corresponding table stems. Stable path IDs 2–11 follow this order:

1. Eve
2. ItemData_C
3. TalkData_C
4. TextData_C
5. SmithData_C
6. ScenesData_C
7. AdventureData_C
8. AdventureLvData_C
9. NpcData_C
10. NpcCareerData_C

- `all-ten.bundle`: all ten unmodified inputs, including event doors and duplicate
  recipe products retained by the runtime candidate oracle.
- `split-root.bundle`: the first six tables, with the exact dependency name
  `split-dependency.bundle`. That dependency contains the last four tables. Evidence
  records the table-to-owning-bundle assignment and the dependency edge separately.
- `missing-path.bundle`: all ten valid TextAssets remain, but the NpcCareerData_C
  container entry is omitted. This is an extraction failure, not a raw parser failure.
- `duplicate-path.bundle`: NpcCareerData_C has two identical exact container entries
  pointing to the same object. A dictionary-only lookup must not accept it.
- `late-invalid.bundle`: all ten paths and objects are structurally valid and nonempty;
  only the final byte of the 21-byte NpcCareerData_C script is removed. Extraction
  succeeds, while late raw-table decoding must reject the candidate atomically.
- `unrelated-duplicate.bundle`: a valid Eve-only bundle. A test can place it outside
  the requesting asset's dependency closure to catch indiscriminate scanning of all
  supplied bundles, or inside that closure to require duplicate-path rejection.
- `external-root.bundle` and `external-target.bundle`: the root contains nine local
  tables plus an external NpcCareerData_C PPtr with file ID1 / path ID11. The target
  contains that valid TextAsset with **no** container mapping. The root dependency
  names the target, and its exact external path is
  `archive:/CAB-runtime-flow/CAB-runtime-flow`. Both directories have the same CAB
  name. Evidence records the full source/target tuples for an explicit binding;
  an orchestrator that does not accept bindings must reject this case.
- `aggregate-overflow.bundle`: all ten original payloads are zero-padded to 3,565,159
  bytes each, totaling 35,651,590 bytes. Each requested script is below 16 MiB and the
  SerializedFile is below 64 MiB, but extraction exceeds the flow's 32 MiB aggregate
  ceiling. The padded raw tables are intentionally invalid and must never be parsed.
  Only compressed bytes and scalar lengths/hashes are retained.

The test-side manifest helper supplies actual manifest records and verified source
handles around these owned bundle bytes. The fixture generator itself does not grant
official trust, invent manifest acceptance, or call production acquisition paths.

## Evidence and regeneration

`Fixtures/evidence.json` includes the pinned input hash; package versions; each
table's exact name/path/ID, payload length and SHA256; each retained bundle's size,
SHA256, serialized-content hash and decoded structure; and explicit scenario maps.
The shape for test-side verification is `files[filename].sha256` / `.bytes`, plus
the `tables` array for the original payload hashes. Malformed/padded script hashes
are recorded under the corresponding file's `scripts` array.

From the repository root, with the pinned packages already installed:

    PYTHONPATH=<installed-package-directory> python dotnet/Lala.Core.Tests/Resources/RuntimeFlow/generate_runtime_flow_fixtures.py

Run twice and compare every retained file, including evidence, to verify deterministic
regeneration. The generator performs no installs and does not invoke .NET. All ten
bundles together occupy 160,919 bytes; the aggregate-budget case is 144,944 bytes of
that total. Evidence is ordinary JSON and does not embed the enlarged raw payloads.

## Connected offline flow

`OfflineBundleRuntimePreparation` is internal and calls the real source preparer,
native UnityFS extractor, and ten-table decoder. There is no replacement-decoder
callback and no production HTTP or filesystem implementation.

The source preparer reads both actual manifest bodies, checks their versions and
hash receipts, builds the required aggregate plan, verifies every selected bundle's
length/MD5/CRC, and returns private owned-byte handles. The plan also retains each
individual asset's exact root plus its manifest-listed complete dependency set.
Those sets are not recursively expanded. Extraction uses the individual set,
never the union of every selected runtime root, so unrelated containers cannot
silently change duplicate-path semantics. Every required TextAsset is extracted
before any raw table is decoded, in the original ten-table order.

All existing input, download, native parsing and table limits remain mandatory.
A new conservative 32 MiB ceiling bounds aggregate extracted table ownership in
addition to the existing 16 MiB per-table limit and 32 MiB total acquired-source limit.
This can reject unusually large source-valid tables and is an explicit safety
restriction, not Python parity. There are at most ten extraction operations; each
retains the native extractor's independent compressed/expanded/object limits.

After successful raw decoding, the flow performs a fresh version observation,
rereads both complete manifest `.hash`/`.bytes` responses, compares them to the
original parsed contents, and observes versions again. This extends the existing
preparer checks across decoding rather than pretending a pre-decoding observation
covered later work. The additional trailing observation protects the scripted
manifest reread interval. Neither a caller's digest claim nor the metadata-only
CatalogKey substitutes for these actual bytes. At the final return, the same
preparation owner/attempt is checked under its generation lock. A superseded or
invalidated operation cannot return a late candidate. A returned result is a
historical observation, never a promise that remote versions will remain unchanged.

All raw bundles and extracted tables are owned; cache streams are not reopened
for extraction. Source/cache mutation after acquisition cannot change decoding.
Every failure or cancellation returns no partial result and does not mutate a
previous candidate. Responses are disposed through all exits. No active catalog,
cache file, database receipt, source installation or AccountSession state changes.

The flow deliberately rejects external PPtrs without guessing an allowlist from
manifest dependency names. Official provenance, database-byte admission, static 1275
runtime hash/count gates and runtime installation stay explicitly unavailable.
Optional SkillData, portal metadata, images, daily/guild/Ark and other catalogs retain
the ten-table candidate's unavailable status. Event-portal reconciliation/conflicts/
coverage, actual-source acceptance, Android/AOT and live-server readiness are not
completed by this wiring.

Focused tests exercise the actual owned fixtures through the complete flow, including
cache/source mutation, late version and matching-CRC manifest replacement, source
ordering, exact per-asset dependency isolation, missing/duplicate containers, late
career decoding rejection, an unresolved external target, aggregate byte budgets,
cancellation, invalidation and deterministic supersession after decoding. Existing
BundleSource tests retain actual Python manifest/plan/digest parity and source pins;
existing RuntimeCandidate and Unity tests retain parser/layout parity. This suite
adds orchestration contract evidence, not full Python runtime or CDN parity.

## Verification receipt

**100 focused Release tests passed**: 19 new owned-flow contract cases and 81 existing
BundleSource cases, zero skipped. Compilation had zero warnings/errors on the final
run, using the existing process-only 3 GiB GC cap and writable SDK/cache environment.
Independent source/security review approved the final code and tests. All 11 fixture
files reproduced byte-for-byte in repeated complete UnityPy regeneration; the
fixture generator also passes Python compilation. The first compile exposed a
test constructor ambiguity/unassigned hook, and one initial test incorrectly rejected
FrozenDictionary's read-only IDictionary compatibility surface; both test issues
were corrected before the passing run. Full integrated regression is delegated to
the integrating branch and is not claimed by this focused receipt.
