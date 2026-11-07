# Reviewed combat catalog, offline subset

Ports `_block`, `_enum`, `parse_constants` and `build_catalog` from the retained
`wlre/services/world/combat_catalog.py`. `SkillDataParser`, `ItemDataParser` and
`NormalAttackCatalogParser` are reused without changing their public contracts.
`load_verified_catalog`, downloads, Lua execution/decryption, normalized caches,
runtime activation, UI/session wiring and outbound commands are not implemented.

## Source and data boundaries

- Public entrypoints retain all five fixed reviewed SHA-256 pins: ItemData, NPC,
  SkillData, clear `Define.lua` and clear `FightUnit.lua`. The two clear Lua pins
  are from `official_lua_codec.KNOWN_FILES`, not its encrypted-file hashes.
- Lua hashes use strict UTF-8 of the exact supplied string. No BOM removal,
  newline conversion, Unicode normalization or replacement of invalid surrogates
  occurs. The inherited official codec's 2 MiB ceiling is also applied here.
- Source build order is item hash, NPC validator and reread, item parser, skill
  parser, all required names, nonzero key uniqueness, then Lua hashes/constants.
  In particular, NPC layout errors precede ItemData layout errors after the item
  pin has passed. Names need to be nonempty strings; whitespace and NUL remain,
  and duplicate display names are allowed. No trimming or guessed name fallback.
- All 71 unsigned skill fields survive. NPC names retain the source's trailing-NUL
  removal, and all five skill slots come from byte 75 of the 203-byte record.
  Items retain name, kind, both complete attribute records (including effect),
  special, restrict, skill link and fit type.
- Constants use a literal scanner equivalent to the source's restricted regular
  expressions. It is not a general Lua parser. Comments and quoted braces are
  not removed. First matching blocks/fields, decimal token prefixes, Unicode
  word/digit characters, source whitespace, and nested brace counting remain.
  Duplicate enum keys reject before integer conversion. Duplicate matrix rows,
  cells and numeric enum aliases retain the source's last-write-wins behavior.
  The final matrix must have exactly keys 0 through 4 on both axes. Character
  indices must be sequential 1 through 15, with all required fields and enum
  references present. Character numeric values use BigInteger instead of clamps.
- Outputs and nested collections are immutable. No public method takes custom
  source hashes or selects an unverified layout. Internal layout helpers exist
  solely for synthetic tests and cannot be used as proof of official resources.

## Existing knowledge DTO projection

`CombatCatalogData.ToKnowledgeSnapshot` explicitly produces the existing
`CombatResourceCatalog`, which remains caller-supplied, unverified offline data.
It does not prove a package identity or authorize actions. The full parsed items
retain fields absent from the older DTO: item name, special and attribute effect.
Those fields are intentionally absent from the knowledge projection, not lost
from the catalog. Characters outside the DTO's int/uint/ushort ranges and
nonfinite weights reject projection instead of wrapping, clamping or defaulting.
The raw constants preserve Python's large integers and float overflow to infinity.

## Differential tests and explicit typed differences

Run from the repository root:

```sh
python dotnet/Lala.Core.Tests/Catalogs/Combat/generate_combat_catalog_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~CombatCatalogTests
```

The 195-vector generator calls actual retained Python functions/decorators. Synthetic pins
are substituted only inside `mock.patch` contexts and asserted restored after
*each* call. Unchanged-pin public rejection cases remain separate. No official
asset success-path testing is claimed. Fixtures retain raw source results,
exception classes/messages and all source diagnostics. C# differences are named
separately rather than rewriting Python expected outputs:

- Binary IDs are typed numeric dictionary keys instead of canonical decimal
  strings. Skill fields fit losslessly in the existing Int64 field dictionary.
- The signature takes the two known Lua strings directly, and text IDs map to
  nullable strings. Arbitrary Python object types/absent clear-map entries are
  not admitted through that typed API. Missing/null/empty names still reject.
- Source KeyError for an unknown enum reference becomes a value-free
  CatalogDecodeException. Invalid float tokens also use a value-free error,
  rather than embedding input contents in exceptions or diagnostics.
- Existing SkillDataParser's public Parse admits size before checking its fixed
  hash, whereas Python parse_skills checks the hash first. Its public fingerprint
  rejection uses the inherited English label rather than the source's Chinese
  label. This is an inherited public-parser gate/error difference, distinct from
  the preserved overall catalog stage order and the synthetic layout cases.
  Its layout path rejects fewer-than-four bytes as an invalid record size rather
  than Python struct.error. Existing ItemDataParser truncation keeps
  its established `Catalog record truncated` message. Fixtures mark only those
  specific inherited differences.
- BigInteger conversion retains CPython's default 4,300 decimal-digit ceiling,
  with a stable value-free error. The ceiling counts digits, not UTF-16 units.
- The knowledge projection's checked ranges and finite weights are deliberate
  typed restrictions, tested separately from raw parse results.

The generated resources are deterministic gzip JSON with explicit resource names,
WithCulture=false, and compressed/decoded SHA-256 checks. C# contains no base64
literal payloads. Each checked-in file is below 500,000 bytes with either LF or
CRLF text checkout. Only retained Python *source-file fingerprints* normalize
CRLF to LF; resource hashes and runtime Lua text never do.

Focused Release verification passes **2,869/2,869** tests across Catalogs and
CombatResourceKnowledge, including **208** tests in this increment. The retained
Python regression command passes 20 tests and skips one existing private-asset
case. Fixture/source metadata regeneration is byte-identical; diff whitespace and
500,000-byte LF/CRLF file checks pass. No official assets were supplied or fetched.

## Diagnostic scope and remaining gaps

The source does not decorate constants or the overall catalog builder, so no new
aggregate events are invented. The existing NPC parser retains its source
observation and checkpoints. The secondary NPC reread also preserves source
checkpoints in an enclosing diagnosed call; three retained-Python regressions
check the exact parent failure location after names, keys or constants fail.
The reused C# ItemDataParser and SkillDataParser
still lack their source decorators. Raw oracle observations retain that evidence,
and tests compare the NPC observations actually supported by this increment.
This is not full diagnostic parity, runtime integration or official acceptance.
