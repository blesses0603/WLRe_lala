# Offline five-feature source adapters

Ports `wlre/services/world/catalog_adapters.py` into a bounded offline composition API:

- `CatalogSourceContract` validates feature/schema pairs, source names, lowercase SHA-256, package names and version strings.
- `CatalogSourceAdapters.ParseFeature` checks catalog key, package version, nonempty 16 MiB payload limit and supplied SHA-256 in source order, then decodes the selected schema.
- `CatalogSourceAdapters.ParseSelected` requires exactly five contracts and returns every feature in the source order `npc`, `shops`, `crafting`, `scenes`, `items`. A missing or invalid late source throws without returning a partial set. Extra payloads are ignored, while extra contracts fail. The historic source error wording “All four” is intentionally preserved.

The actual existing ItemData, Smith and Stage decoders are composed, rather than duplicated. NPC/shop derived JSON can directly consume `EveV115Indexes.ToJsonUtf8`; schema/source, scene IDs, row counts, event indices, NPC fields, shop forms and item fields are validated. Extra JSON fields and their order are retained as immutable owned `JsonElement` rows. Duplicate JSON properties retain the first position and last value, as in Python dictionaries.

The `smith-reviewed-v1` selector is **not** `SmithDataParser.ParseRecords`. Its 33-byte branch returns an **unmarked keyed map**, while its 35-byte branch returns a **timed-marked array** that permits duplicate output IDs. Zero rows choose the 33-byte branch. Adapter schemas remain distinct from underlying parser diagnostic schemas.

## Authority and exclusions

**Caller-supplied checksums, package versions, contracts and catalog keys are validation inputs, not proof of independently reviewed provenance.** Every parsed feature has permanently false `AssetsReady` and `CanSendPackets`. Results do not update `State.IsComplete`, accept resources, activate a runtime or authorize packet sending. No runtime/store/network/UI/Android/AccountSession changes occur.

The ItemData adapter uses a new **internal adapter-only** ordered and diagnosed path sharing the existing layout implementation. Its independent fixed 1296 SHA-256 is unchanged. Per Python, the adapter does not pass the outer contract's package version into the ItemData parser. Caller hashes cannot unlock reviewed ItemData fields or bypass its fixed pin. Existing public ItemData signatures, frozen-map return behavior, validation order and diagnostic behavior are unchanged. This does **not** complete the unrelated global ItemData diagnostic gap in existing combat/normal-attack callers.

No resources are downloaded or extracted, and there is no storage or runtime integration. Official-source success, ten-table resource completeness, game login, live server behavior, or device acceptance are not claimed.

## Diagnostics and deliberate typed boundaries

The actual decorated Python oracle retains successful results, raw error strings, attached failures and complete emitted observations. Feature success has a null diagnostic record count because Python's result is a dataclass; selected success reports five. Nested successes remain suppressed. Nested failures remain separate observations, and adapter wrapping uses the exact generic source error without retaining the child exception or payload. Outer adapter failures do not inherit child cursor positions.

- Python `CatalogAdapterError` becomes `CatalogAdapterException`. Child `ItemDataDecodeError`, `PreviewError`, `ValueError` and `ProtocolError` become the existing `CatalogDecodeException`. Exact adapter messages and source diagnostic locations are preserved; diagnostic error-type names use these CLR types. Inner exceptions are intentionally omitted.
- `ReadOnlySpan<byte>`, nullable strings, typed contracts and read-only mappings replace Python dynamic types. Arbitrary non-byte inputs and non-string constructor values are outside the API. Empty spans receive the source empty-payload error. Contract fields are get-only and cannot be mutated or reconstructed with validation bypasses.
- JSON is restricted to strict UTF-8/RFC JSON, nesting at most 64 and finite floating values. Python-specific `NaN`/`Infinity`, overflow-to-infinity numbers and unpaired Unicode escapes are rejected with `Invalid UTF-8/JSON index`. These are explicit stricter input boundaries, not claims of full dynamic Python JSON acceptance. Python's default 4,300-digit integer limit is preserved, including ignored or overwritten values. Exact integer validation rejects booleans and floating literals for row/count fields, while `schema_version` preserves Python equality acceptance of `true` and `1.0`.
- Source names and package versions count Unicode scalars, preserving Python lengths for valid Unicode, rather than UTF-16 code units.
- Maps have separate immutable key order and frozen lookup; binary rows are fixed-schema immutable values. JSON is normalized, cloned, and detached from input bytes and disposed parser documents. No mutable arrays/dictionaries are exposed.
- Cooperative cancellation is added before validation, between features, during hashing/record traversal and before returning. It propagates without becoming a parser failure. JSON parsing itself is a bounded synchronous framework operation, with checks before and after it.

## Retained acceptance evidence

The generator retains 601 actual decorated Python cases in seven deterministic compressed resources, with compressed and decoded hashes and seven CRLF-only-normalized source fingerprints. Cases cover all schemas, constructor and key/version/hash/size gates, JSON validation and extras, duplicate-key behavior, binary framing, nested parser errors, maximum row counts, and every feature's missing/invalid/late-failure placement in the five-feature pipeline.

Discovery carries only a short ASCII case ID and two integer coordinates; resources load lazily during execution. Maximum inputs use compact recipes; full ordered dataclass JSON output hashes cover every retained row and field rather than only counts/endpoints. Other successful cases retain complete results with recursive key-order comparison.

Additional C# contracts exercise EVE-index-to-adapter composition, owned sliced inputs, immutable ordered results, cancellation, oversize no-copy rejection and precedence, strict JSON boundaries, source fingerprint verification and bounded discovery. Existing ItemData, normal-attack and combat tests are included as regressions.

Reproduce from repository root:

```sh
python dotnet/Lala.Core.Tests/Catalogs/SourceAdapters/generate_source_adapter_vectors.py
PYTHONPATH=tests python -m unittest test_catalog_adapters test_itemdata_v1 test_smith_candidate test_instance_catalog_1262 test_preview_1275 -q
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter 'FullyQualifiedName~SourceAdapters|FullyQualifiedName~CatalogParserTests|FullyQualifiedName~NormalAttack|FullyQualifiedName~Catalogs.Combat'
```

Independent static review compared the complete source implementation, fixture materializers/projections, ordered hashes, ownership and authority boundaries. Final focused Release verification passed **2,274 tests**, with zero failures or skips, across the adapter suite and existing ItemData/catalog, normal-attack and combat regressions. The five original Python suites ran **36 tests: 35 passed and one private official-bundle test was skipped** because no private bundle was supplied. The fixtures regenerated byte-identically. A focused pass does not imply aggregate or production acceptance.
