# Required raw-table decoders (offline only)

This increment ports actual Python source functions, not a second NPC interpretation:

- `npc_talk.parse_talk_data`: signed i32 count, u16 ID and UTF-16 byte length, strict text validation and trailing-NUL removal, every reserved tail byte consumed, voice ID, source insertion order, duplicate/control rejection order and exact EOF.
- `expedition.data.parse_catalog`: complete 105-byte AdventureData rows (all conditions, four recommendations, three rewards, special reward, signed EXP), 15-byte AdventureLv rows, source hashes, validation after complete rows, task-before-level failure precedence.
- `expedition.data.parse_npcs`: complete career table and EOF before NPC header; 17-byte career rows mapping career to original; two strict u16-byte-length strings and 203 fixed fields per NPC. Returns element, kind and original ID. Zero original and absent target rows are allowed by source. This is not `NormalAttackCatalogParser`'s projection or reviewed-source path.
- `expedition.data.attach_names`: reuses `TextDataParser`, rejects missing/empty names but permits whitespace and NUL names, defaults absent areas to empty, retains text exactly and appends the TextData hash.
- `OfflineRuntimeTableDecoder`: composes only the six supplied Talk, Text, Adventure, AdventureLv, NPC and career tables. It preserves their relative source parse order and the runtime name-binding block's stricter nonblank names / 8192 Unicode-codepoint name and area limits. Python whitespace semantics include U+001C..U+001F. It adds the NPC/career hashes, not an invented TextData hash, matching that block.

The composition accepts extracted bytes only, limits each required source to 16 MiB, rejects a missing/oversized source when its stage is reached and ignores unrelated table keys. Caller maps and content hashes confer no provenance. `SourceKind` is `supplied_offline_tables`; verified-provenance, assets-ready, send and runtime-admitted properties are always false. Existing fixed pins are unchanged and no public caller hash can override them. This is not static/dynamic runtime installation or full ten-table runtime parity. Eve door projection, extraction, source admission, fixed-version runtime hash/count policy, storage/cache, networking, UI, Android and AccountSession are outside this scope.

## Typed boundaries and cancellation

Python decimal-string task/NPC keys become `ushort`; level keys become `byte`; Talk keys remain `ushort`; Text keys remain `uint`. Signed i32 counts/EXP and unsigned field widths remain exact. Models are internally constructed, immutable and owned; nested arrays are immutable and dictionaries preserve source order. Python's unsupported dynamic object types, dictionary mutation and malformed caller catalog shapes are not emulated. `AttachNames` accepts only a parser-produced immutable catalog. Nonempty but whitespace-only strings differ intentionally between attach and strict runtime binding, exactly as in source.

Python `ValueError`, `ProtocolError` and runtime binding rejection become `CatalogDecodeException` with exact source messages. NPC strings' uncaught Python `UnicodeDecodeError` becomes `DecoderFallbackException`; its platform-specific codec message is not asserted. All parser IDs, schemas, numeric cursor/checkpoint values, exact source input names/digests, nested observation semantics and event order are retained. Attach/composition do not invent their own diagnosed parser. Results and diagnostics never authorize resource use.

The raw expedition parsers retain source record/u16-string limits, rather than silently adding the composition's 16 MiB input ceiling. All APIs add cooperative cancellation before validation, during reads/loops/hashes and before returning results. Cancellation raises `OperationCanceledException`, records no parser failure and never returns a partial catalog. Python has no corresponding cancellation API. No callbacks, files, reports or caches are activated by these parsers.

## Retained evidence

`generate_required_table_vectors.py` calls the actual decorated Python functions in an in-memory diagnostic run. Strict composition uses the exact AST statements for runtime name binding, with supplied parsed rows. It excludes the enclosing source-verification, fixed-hash/count checks, caches and activation. Expected trusted-runtime revision/source labels are explicitly removed only when comparing that block to the intentionally unverified C# result.

Fixtures cover every truncation position, fields/ranges, empty/invalid Unicode, duplicates and absence, join direction and precedence, source/result ordering, reserved bytes, attach-versus-strict names, non-BMP 8192/8193 boundaries and full accepted record limits. Large accepted bounds retain reproducible recipes plus a full ordered typed-binary result digest, rather than giant retained JSON. Summary encoding tags every scalar, list and insertion-ordered map; dictionary keys are their source strings and all fields participate. C# streams these result digests one row at a time.

Deterministic gzip resources and their decoded content both have retained SHA-256 hashes. Five source hashes normalize CRLF only. Discovery enumerates scalar numeric case IDs; lazy runtime lookup loads the checked compressed resource. Handwritten tests additionally exercise mutation/ownership, nested immutability, cancellation, source-map precedence/bounds, pin separation and payload-free diagnostics.

Regenerate from the repository root:

```sh
python dotnet/Lala.Core.Tests/Catalogs/RequiredTables/generate_required_table_vectors.py
```

Focused tests (requires .NET 10):

```sh
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~RequiredTables
```

Verification for this increment: **1,256 focused Release tests passed** (1,239 retained actual-Python vectors, five CRLF-only source-hash checks and twelve boundary facts). Independent read-only review approved before commit. Three oracle generations produced identical resources and metadata. This is a focused decoder result, not an aggregate application/device/live-server pass.
