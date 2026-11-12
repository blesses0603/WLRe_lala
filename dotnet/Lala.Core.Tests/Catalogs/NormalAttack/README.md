# Reviewed normal-attack catalog subset

This offline increment ports only `parse_npcs` and `build_catalog` from the retained
`wlre/services/world/normal_attack_catalog.py`. It does not port `_source` or
`CurrentNormalData`, retrieve official resources, activate runtime catalogs, send
commands, grant capture/attack permissions, or change UI/session behavior.

## Production contract

- `NormalAttackCatalogParser.ParseNpcs` preserves the fixed NPC SHA-256 pin.
- `BuildCatalog` first verifies the fixed reviewed ItemData SHA-256, then reuses
  `ItemDataParser` before parsing NPCs. No public caller-supplied hash, layout
  option, legacy ItemData fallback, or verification bypass is exposed.
- NPC strings are strictly UTF-16LE validated even though they are discarded.
  Empty and NUL-only strings are allowed. The 203-byte field block retains only
  ID at byte 1, capture flag at 26, body type at 27, kind at 106, and normal attack
  kind at 114. Capture is allowed by the source flag exactly when byte 26 is zero.
- Zero/duplicate IDs, invalid counts, truncation, malformed text and trailing bytes
  fail closed. The total NPC byte limit is derived from the source's 20,000-record
  and two 8,192-byte text limits, not from a guessed official file size.
- Catch nets select `special == 140` and subtract 100 from the **first** signed
  Int32 attribute value. Int64 results preserve Python arithmetic at both extremes.
- Immutable catalog output includes capture facts and an explicit existing
  `Battle.NormalAttackCatalogSnapshot`. This snapshot is data, never authorization.

## Differential evidence

Run from the repository root:

```sh
python dotnet/Lala.Core.Tests/Catalogs/NormalAttack/generate_normal_attack_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~NormalAttackCatalogTests
```

The 810 vectors call the actual retained Python functions/decorators. For synthetic
layout cases only, the generator temporarily substitutes module-level digest pins
inside `mock.patch` contexts and verifies that they are restored after each call.
Separate public-input cases run the unchanged Python pins. C# public entrypoints
also reject every synthetic fixture; only internal test layout helpers bypass
digest gates. No official asset success-path validation is claimed.

Coverage includes every NPC fixed-byte position, all truncation points in complete
NPC/Item records, invalid Unicode and length limits, maximum record counts,
duplicate/zero IDs, error ordering, unsigned field limits, signed catch-net
extremes, immutable projections, cancellation and diagnostic privacy/concurrency.
Fixtures are deterministic gzip JSON embedded resources with both compressed and
decoded SHA-256 checks. Generated C# has no embedded base64 payload strings.
Source hashes normalize CRLF to LF, so Windows checkouts preserve the same evidence.
Theory discovery receives only a bounded case name and fixture/row indices. Actual
payloads are loaded from verified resources at execution time, using one private
thread-safe lazy cache of immutable detached JSON roots per test assembly. Large
records never enter test display names, and repeated lookups do not decompress the
same resource again.

Focused Release verification passes **825/825** tests. Retained Python checks pass
14 diagnostic tests and 10 ItemData/normal-attack tests, with one existing
asset-dependent ItemData test skipped. Deterministic regeneration is byte-identical.

## Diagnostic scope and remaining gap

NPC `@diagnosed('normal-npc-reviewed-1296')` behavior reuses existing optional
`ParserDiagnostics`, including source read checkpoints, text-length constraints,
input digests, record counts, failure annotations and nested-call semantics.
Tests compare real Python NPC observations, mapping Python `ValueError` and
`ItemDataDecodeError` labels to the established C# `CatalogDecodeException`.
No input strings, raw bytes or exception messages enter the reports.

`build_catalog` itself has no source decorator. Its nested ItemData observation is
still absent because the existing C# `ItemDataParser` instrumentation is outside
this increment. That gap is explicit; this is not full-module or full-diagnostic
parity. No other parser, shared reader, battle planner or display code is changed.
The inherited ItemData truncation error uses `Catalog record truncated`, while
Python says `ItemData record truncated`. Oracle tests map exactly this error only
when ItemData failed before NPC parsing. NPC truncation preserves source wording;
all other rejection messages are compared exactly.
