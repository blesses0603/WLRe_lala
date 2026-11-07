# Read-only Eve v115 index parser

Source scope: `wlre/services/world/eve_v115.py`, including `_common`, `_npc`,
`_interact`, the event/group/battle skip layouts, the entire eleven-section scene
walk and exact offset-table verification, both single-index and combined-index
entry points. No retired coordinate/navigation source or live game asset is used.
The parser reads caller-provided bytes only. It has no file/network calls, cache,
resource activation, packet authorization, event execution or session integration.

`EveV115Parser.Parse` returns immutable typed scene/NPC/interaction observations.
The overload with a source retains only that source but still validates every
scene and all eleven sections, including unselected NPC IDs and duplicate row
indexes. `DeriveIndex`, `DeriveIndexes` and `ToJsonUtf8` emit the exact schema-v1
UTF-8 bytes from Python (`sort_keys=True`, ASCII escaping, compact separators).
Typed scenes use numeric order, while JSON scene properties use Python's final
lexicographic string-key order. Unknown fields and names are skipped, never
interpreted as commands or exposed in diagnostics.

## Limits and failures

- Input length: 12 bytes through 16 MiB, checked before copying caller memory.
- Scene count: 1 through 4,096. Header offsets use overflow-safe arithmetic;
  scene ranges cannot overlap or read into another scene.
- Each of eleven per-scene section counts: at most 4,096.
- Selected records: at most 20,000 independently for NPCs and interactions,
  checked after each full scene, as in Python. Unselected rows are validated
  without retaining their event/item arrays. All nested lengths are byte/ushort
  counts bounded again by the verified scene segment and overall input cap.
- Source-sized input, scene IDs, per-section duplicate sets, selected row/item
  builders and output are all bounded. Each interaction item occupies five input
  bytes, so the 16 MiB source cap additionally bounds nested retained items;
  items use value types to avoid one object allocation per item. JSON output can
  be larger than input. No separate smaller output cap changes accepted syntax.
- Cancellation is checked before allocation, for every binary read/skip, each
  scene/header, each emitted row/item, bounded zero-tail scan chunks and before
  returning immutable bytes. Cancellation throws rather than publishing a partial
  index. Source bytes are snapshotted once and never retained by the result.
- `EveDecodeException` preserves the source's bounded error text. Optional typed
  location data has only numeric positions/counts and a code-owned section enum.
  It never contains payload bytes, names, filesystem paths, or inner exceptions.
  This is not a port of diagnostics report persistence/session machinery.

### Deliberate fail-closed divergence

The retained Python duplicate-scene check tests an integer against a dictionary
with string keys. It therefore accepts two nonoverlapping scenes with the same
ID, overwrites one scene's rows, and counts both in `record_count`. C# rejects
these duplicate IDs during header validation. Three explicit oracle fixtures
show Python's inconsistent result and assert rejection; they are not claimed as
parity-passed accepted inputs. Python source is unchanged.

Other source behavior is preserved, including accepted scene/index ID zero,
ignored model-ID mismatches, opaque first eight bytes, gaps and bytes outside
scene ranges. Successful syntax parsing does not establish authenticity or
resource identity; caller-side manifest/bundle verification remains required.

## Offline evidence and reproduction

`generate_eve_vectors.py` constructs synthetic bytes and invokes the actual
retained Python entry points. It does not reimplement expected decoding, patch
source limits, download resources, write diagnostics, or access a live session.
Source provenance includes SHA-256 of `read_bytes()` and a separately labelled
canonical CRLF-byte hash. The source at this commit uses LF; no text-reading
newline normalization is mistaken for a raw source hash.

The 2,146 generated cases cover all variable-length paths, unsigned extremes,
all eleven skip/decoded sections, every byte of a complete multi-section scene
as a segment truncation, file truncations, unsupported versions/forms, corrupted
section tables, all count limits, independent selected-index totals, unknown
sources, duplicate row IDs, header/byte/numeric/lexical scene ordering, gaps,
tails, and seeded accepted layouts. The whole-source 16 MiB cases use an explicit
zero-padding descriptor to avoid storing giant repeated Base64 literals.
Exact success bytes and exact source exception messages are compared, except
for the three clearly marked duplicate-scene rejection cases.

Generated payloads use the shared deterministic gzip helper with fixed
timestamp/name/OS metadata. Fifty-one `.json.gz` binary EmbeddedResources avoid
both the C# syntax-tree cost and the assembly user-string heap. Logical names
are explicit and stable on Windows/macOS/Linux. Every resource is below 500,000
bytes and has compressed and decoded SHA-256 checks in the small C# wrapper.
`GzipJson.DecodeResource` bounds both input and decompressed sizes; directed
tests cover missing/corrupt/truncated resources, wrong hashes, size limits and
strict UTF-8. Its existing byte-array API is unchanged. The shared Python
`gzip_json_bytes` helper also preserves the existing byte-literal generator.
No fixture changes production or repository test execution policies.

```sh
PYTHONPATH=/tmp/daily-assistant-deps python dotnet/Lala.Core.Tests/World/Eve/generate_eve_vectors.py
PYTHONPATH=/tmp/daily-assistant-deps python -m unittest tests.test_eve_v115
cd dotnet
dotnet test Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~EveV115Tests
dotnet test Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
```

Verified on the Linux .NET 10 environment at the `349fda1` baseline plus this
slice: **2,159/2,159 focused Eve/loader tests**, **21,445/21,445 full Core tests**,
and **12/12 retained Python tests**. The reusable fixture-infrastructure commit
also builds independently with **5/5 loader tests** in a clean checkout. Resource
regeneration is byte-for-byte deterministic; representative existing byte-literal
helper outputs are unchanged. The platform-independent resource-name test is
included for Windows/macOS/Linux CI, but this run did not execute Windows/macOS.

Still outside scope: official asset provenance/downloads, Unity/manifest loading,
index persistence, NPC/shop adapters, event or door/convey semantics, resource
activation, diagnostics persistence, live movement/coordinate use, command
execution, AccountSession/coordinator/transport/UI integration, Android and
real-server/device acceptance. No migration inventory or shared docs are changed.
