# TextData and NPC battle-talk offline parity

Ports only these actual Python functions:

- `wlre.services.expedition.data.parse_text_data` → `TextDataParser.Parse`.
- `wlre.services.world.npc_battle_catalog.parse_known_battle_talk` → `NpcBattleTalkCatalogParser.ParseKnownBattleTalk`.
- `wlre.services.world.npc_battle_catalog.build_catalog` → `NpcBattleTalkCatalogParser.BuildCatalog`.

TextData accepts more than four and at most 16 MiB, a signed Int32 count of 1–1,000,000, UInt32 keys, and UInt16 byte lengths. Strict UTF-16LE decoding retains empty strings, zero keys, BOMs, and every NUL. It does not reuse the unrelated 8,192-byte ItemData limit or trim strings. Duplicate keys, odd lengths, malformed Unicode, truncation, and trailing bytes fail closed.

Production battle-talk entrypoints retain the fixed SHA-256 `9de2f789e7f194148959457e7a1fc4744bf3378d62fdaff54ce51efe28499bb8`. The count is 1–20,000 and the exact row width is 10 bytes (`<HIBHB`). Group/text IDs must be nonzero, and each group has at most 255 rows. Group order is stored explicitly, separate from frozen lookup; rows remain in source order. Duplicate quote rows are valid. Internal-only layout entrypoints support synthetic tests; there is no public pin override.

The builder parses quotes, then TextData, then checks for missing references, in that order. Empty referenced strings are valid. It returns only the quote groups, as Python does. It does not attach decoded text or certify that any supplied TextData belongs to an official revision.

## Retained evidence

`generate_text_battle_talk_vectors.py` invokes the actual **decorated** Python functions, not an expected-result reimplementation. Its 295 synthetic vectors cover every truncation of representative text and quote tables, signed/count/size boundaries, maximal strings, invalid surrogates, empty/zero/NUL/BOM cases, duplicate IDs and rows, group/row order, maximum row/group counts, builder ordering and missing/empty references, and unchanged-pin public rejection. Six deterministic gzip resources retain results, failures, and all emitted diagnostics. Resource hashes validate both compressed and decoded bytes. Source hashes normalize only CRLF to LF.

The valid million-record and exact 16-MiB vectors retain deterministic input recipes rather than oversized binary literals. Their expected digests are computed from the actual Python result, covering every ordered key and every UTF-16 code unit. Other successful vectors retain complete results. Every theory receives only a short name and two integer resource coordinates. JSON is loaded inside test execution, never passed into discovery/display names.

The `text-v1` and `npc-battle-talk-known-v1` schemas, parser IDs, input names, counts, digest values, failure cursor fields, and builder's lack of a decorator remain unchanged. The internal span diagnostics helper adds only an optional code-owned input name, defaulting to the previous `raw`; TextData uses its source name `text_data`. Contract tests additionally cover immutable owned results, sliced input, cancellation, nested/concurrent diagnostics, failure identity, privacy, input release, and bounded discovery arguments.

### Explicit typed deltas

- Python `ProtocolError` and `ValueError` become Core `CatalogDecodeException`; error messages are preserved, and diagnostic `error_type` is mapped to that CLR type. Decoder exception objects/messages are not retained.
- `ReadOnlySpan<byte>` replaces Python's dynamic exact-`bytes` input gate. Python wrong-type calls are outside this typed API; empty/default spans still fail the binary contract.
- Results are owned read-only maps, immutable quote arrays, and immutable row records rather than mutable Python dictionaries/lists. NPC ordering is explicit, not delegated to frozen-map enumeration.
- Cooperative `CancellationToken` handling is added. Cancellation precedes parsing and is never a parser/layout failure.
- Diagnostics remain optional and in memory. No report files or resource state are written.

## Reproduction

From the repository root:

```sh
python dotnet/Lala.Core.Tests/Catalogs/TextBattleTalk/generate_text_battle_talk_vectors.py
PYTHONPATH=tests python -m unittest test_npc_battle_catalog test_automatic_candidate_indexes test_dynamic_bundle_runtime -q
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~TextBattleTalk
```

The focused Release suite passes all **309 tests** (295 retained parity cases, four source hashes, and ten contracts). The three original Python suites contain 31 passing tests, including surrounding runtime tests; those passes do **not** claim their runtime/storage features were ported. Independent read-only review regenerated all fixtures in memory and verified exact compressed/decoded identities.

## Excluded and unverified

No `load_verified_catalog`, localization runtime, bundle extraction/download, SQLite/cache installation, official source fetch, global current catalog, UI/Android/session integration, command transmission, or gameplay readiness. No existing `IsCompleteState` or authorization behavior changes. Public success with the actual pinned official source remains unverified because this suite contains synthetic inputs only. A successful synthetic parse, text-reference join, or diagnostic observation is not production acceptance.
