# Offline Smith and Stage catalogs

This slice ports only these existing Python functions:

| Python source | Core entrypoint |
| --- | --- |
| `world.preview_1275.parse_smith_1275` | `SmithDataParser.Parse33` |
| `world.smith_candidate.parse_smith_candidate` | `SmithDataParser.ParseCandidate` |
| `world.smith_candidate.mark_timed_recipes` | `SmithDataParser.MarkTimedRecipes` |
| `world.smith_candidate.parse_smith_records` | `SmithDataParser.ParseRecords` |
| `instance_catalog.parse_stages` | `StageDataParser.Parse` |

Smith accepts signed counts of 0–20,000 and exact 33/35-byte rows. The 33-byte map rejects zero/duplicate output IDs. Candidate rows require nonzero unique leading recipe keys while preserving multiple recipes for one output. All returned recipe fields, material-slot order, duplicate materials, and zero amounts are preserved. Zero material IDs are omitted. The source's `material_count` byte must be at most five, but **does not truncate the five material slots** and is not a returned field. A count of zero selects the 33-byte profile before the 35-byte profile. Timed marking copies rows and sets `read_only` exactly when `time_id != 0`; raw parse results have no such field.

Stage reads the exact 76-byte source layout, retaining all 17 returned fields and explicitly consuming every discarded field. It allows ID zero, rejects duplicate IDs only after reading the whole duplicate row, and checks trailing bytes after all declared records. Truncated reads retain exact source offsets, requested/available byte counts, and raw error text. No whole-input-size precheck changes count, duplicate, truncation, or trailing-byte failure ordering.

Maps keep a separate immutable key sequence and frozen lookup, preserving Python insertion order independently of frozen-map enumeration. Row records and material/recipe arrays are immutable owned results. No returned catalog has source provenance or command authority. In particular, `smith-reviewed-v1` is the unchanged Python structural selector schema, not proof that a resource was reviewed or accepted.

## Retained evidence

The generator invokes the actual decorated Python functions and records results, raw errors, attached failures, and complete emitted diagnostic observations. There are **768 vectors**, with every truncation of representative 33/35/76-byte tables, every truncation of a duplicate Stage row, all field ranges, malformed/zero/maximum/excess counts, unique/duplicate/zero IDs and row keys, material count versus actual slots, timed flags, row/map order, all maximum-record results, failure precedence, and 40 deterministic randomized samples per layout family.

Eight deterministic gzip resources are checked against exact compressed and decoded SHA-256 hashes. Five source-file hashes normalize only CRLF to LF. Test discovery receives only a short ASCII case ID and two integer coordinates. Each resource is loaded lazily during execution, not discovery.

Large boundary inputs use deterministic recipes. Four successful 20,000-record cases retain a SHA-256 of the **entire ordered Python JSON result**, including every returned field, material, and key/row position. C# independently materializes the input and hashes its complete projected result using the same compact numeric JSON representation. All other successful vectors retain complete expected results. This avoids retaining multi-megabyte boundary DOMs while preserving full-result parity, not merely count or endpoint checks.

Schemas, parser IDs, the source input name `data`, counts, digests, and failure locations remain unchanged. Candidate parsing invokes the decorated 33-byte parser on each synthetic single-row buffer; nested successes remain suppressed and nested failures remain separate observations. Reviewed failures retain the source traceback-derived child offset without incorrectly copying the child's field/record into the outer location. Marking itself has no diagnostic decorator.

Additional contracts cover immutable owned sliced-input results, ordered enumeration and lookup, optional-field distinctions, timed copy behavior, invalid typed arrays, pre-cancellation, oversized rejection without an extra copy, nested/concurrent diagnostic isolation, payload/error privacy, weak input release, non-authorizing observations, and bounded discovery arguments.

### Explicit typed deltas

- Python `PreviewError`, `ValueError`, and `ProtocolError` become `CatalogDecodeException`; exact messages remain unchanged and diagnostics map `error_type` to that CLR type. No inner exception payload is retained.
- `ReadOnlySpan<byte>` replaces Python dynamic input types. Exact-`bytes` gates and `Reader(bytes(data))` coercions are outside this typed API; default/empty spans still receive source binary validation.
- Mutable dictionaries/lists become ordered read-only maps, immutable arrays, and fixed-schema records. Nullable `RecipeId`, `CandidateRowKey`, and `ReadOnly` distinguish omitted source fields from zero/false values. No catalog identity, source version claim, or runtime acceptance is inferred.
- `MarkTimedRecipes` accepts only typed parser-shaped recipe arrays. Python arbitrary extra dictionary keys, missing/dynamic `time_id`, booleans, and unbounded/negative integers are outside this API. A default array or null row fails with the source validation message. The helper does not add extra validation to other recipe fields.
- Cooperative cancellation is added before validation and throughout parsing. It is not recorded as parser/layout failure. Diagnostics remain optional and memory-only.

## Reproduction

From the repository root:

```sh
python dotnet/Lala.Core.Tests/Catalogs/SmithStage/generate_smith_stage_vectors.py
PYTHONPATH=tests python -m unittest test_smith_candidate test_instance_catalog_1262 test_preview_1275 -q
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~SmithStage
```

The original Python suites pass all 18 tests. The focused Release C# suite passes all **781 tests** (768 retained vectors, five source hashes, and eight contracts), with zero failures or skips. Independent read-only review reproduced all fixtures and hashes and checked the compact input recipes/full-result digests. No new aggregate-suite or production-resource acceptance is claimed here.

## Excluded and unverified

No catalog adapters, Dungeon/Cooperate catalog builder, verified runtime activation, ZIP/resource extraction, download, installation, storage, live catalog globals, crafting/entry/transfer/send logic, AccountSession, UI, or Android changes. No official resources are included and no positive official-resource/runtime/device/server acceptance is claimed. The missing C# `catalog_adapters.py` integration remains separate work; these results alone cannot activate or authorize it. Its `smith-reviewed-v1` adapter selector must not be replaced blindly with `ParseRecords`: the source adapter returns an unmarked ID-keyed map for 33-byte rows, but a timed-marked array for 35-byte rows. Adapter contract schemas (`smith-new-33-v1`, `smith-new-35-v1`, `stage-new-76-v1`) also remain distinct from the underlying parser diagnostic schemas.
