# Pure skill and field knowledge helpers

This slice ports `learned`, `weapon_group`, `target_valid`, `heal_effects`, and
`field_context` from `wlre/services/items/combat_resources.py`. It consumes the
existing immutable player/companion knowledge and explicit actor observations.
Catalog mappings are caller-supplied, **unverified**, immutable offline data.
Nothing in these results grants catalog, skill-use, account, or transport authority.

## Exact boundaries

- `Learned` preserves insertion order, S8-before-raw-source precedence, first raw
  duplicate mapping, missing-versus-empty S5 records, removed skill evidence,
  identity checks, last matching equipment link, and first novice appearance
  replacement. Equipment may restore a removed skill, and is taken from the actor,
  not the knowledge profile. A newer catalog may remap raw evidence only when a
  caller explicitly invokes the helper with that catalog. No skills are guessed.
- `CompanionProfileSnapshot.SkillOrder` now retains S15/S8 insertion order.
  Replacing an entry keeps its position; remove/re-add appends; S15 replacement
  starts a new order before buffered S8 replay. Imported nonempty player/companion
  maps must provide each current key exactly once in their order arrays. Missing,
  duplicate, extra, or default arrays are rejected instead of guessing dictionary
  enumeration order. The companion collection itself has the same requirement
  when `FieldContext` selects the first active NPC.
- `TargetValid` keeps dead-target exceptions, side/slot comparisons, exited/flying
  exclusion, and Python short-circuit behavior. `HealEffects` describes catalog
  values only. Neither helper changes or estimates any entity's HP/SP.
- `FieldContext` returns a replacement `PlayerKnowledgeSnapshot` containing
  resolved equipment and deferred receive-update replay. **The caller must retain
  that replacement.** The original player, equipment, companion, and catalog
  objects remain unchanged. Field units are a separate projection, not replacement
  live battle state. Companion statistics include source numeric metadata and
  explicit stat overrides; S15 names (including empty names) win over catalog names.
- Unknown role identity stays null, distinct from numeric zero. The pure Python
  field path creates `pid=None` and its profile matcher compares `None == None`.
  `Learned` preserves this behavior for an explicitly supplied null-identity field
  actor; no wire-battle identity, readiness, or permission is implied.
- Malformed typed inputs such as uninitialized arrays, null rows, inconsistent
  order maps, or required missing skill fields are rejected. Arbitrary malformed
  Python object/type coercion is not a supported C# input surface.

The initial five-helper slice did not include `skill_reasons` or `skill_rows`; the
read-only follow-on below adds them. Not included: `learned_command`, `best_skill_command`,
`food_command`, action generation, reservations, schedulers, live catalog loading,
shared coordinator integration, or account/transport/UI behavior.

## Differential verification

`generate_combat_resource_vectors.py` invokes the actual Python helpers with
pinned synthetic catalogs. It emits deterministic gzip **byte** literals rather
than long C# string/base64 payloads. All fixture source files are below 500 KB.
Source fingerprints hash bytes after replacing CRLF with LF only.

The fixtures cover 1,070 uniquely identified cases, including 20 receive histories
with actual Python `apply_live`/local S8 buffering. Histories compare companion
skill insertion order and learned results after every step and recheck retained
immutable C# snapshots. Additional contracts cover malformed imports, sparse
health, source precedence, equipment replacement, null/zero identity, and aliasing.

Regenerate from the repository root:

```sh
PYTHONPATH=/tmp/daily-assistant-deps python dotnet/Lala.Core.Tests/Inventory/generate_combat_resource_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~CombatResource
```

Offline synthetic parity is not official-catalog, live-server, or device acceptance.

Verified for this slice: focused Release tests **1,086/1,086**, full Core Release
regression **20,372/20,372**, and existing Python official-combat/companion-sync
regressions **15/15**. Fixture regeneration is byte-for-byte stable. One concurrent
initial test compilation was killed with compiler exit 137; isolated compilation
with a temporary 2 GiB GC heap bound succeeded. The full test-runtime run used
standard settings. No checked-in build policy was changed.

## Read-only skill validation and display rows follow-on

`CombatResourceKnowledge.SkillReasons` and `SkillRows` additionally port the
source's early gates, ordered diagnostic reasons, weapon/appearance constraints,
SP and HP cost checks, silence/taunt status restrictions, current player inventory
sufficiency, and ordinal category/SP/ID display sorting. Both take an explicit
`BagReceiveSnapshot` and `InventoryPlanningContext`. They call the existing pure
`InventoryPlanning.Allocate`; they do **not** acquire/install reservations, produce
commands, mutate the bag, or reinterpret successful validation as authorization.
Companions skip player item costs. The source's `UseFailed` flag is not invented
as a skill-cost gate; it belongs to other command paths.

Missing catalog rows and missing learned evidence retain the original early
reasons. Missing required fields in a reached catalog branch reject the malformed
import. Passive/life and no-target early exits do not demand fields that Python
never reads. Display rows preserve missing SP as null while using the source's
99999 sort sentinel, an empty catalog name as empty, and source-order learned
collisions before the final ordinal category/numeric sort.

HP consumption diagnostics preserve Python's unbounded integer multiplication,
correctly rounded binary64 true division, and ceiling comparison. A direct cast
of the integer product to double before division is not equivalent: at HP
9007199254740894 and 100%, Python's cost reaches HP, but the double-rounded
calculation incorrectly falls one short. The port rounds an exact rational to a
53-bit ties-to-even significand before applying the binary exponent and ceiling.
It does not infer HP or change the original observed value.

The follow-on oracle executes **928** real Python cases, including full Int64 and
2^53 HP boundaries, adversarial double-rounding cases, all status fight-way values,
companion identity/item-cost skipping, locked/held inventory sufficiency, and row
sorting/fallbacks. `generate_combat_skill_validation_vectors.py` writes separately
bounded deterministic gzip byte fixtures and hashes all source dependencies with
byte-only CRLF normalization. The follow-on also rejects malformed default/null-row
equipment arrays in imported active companion field projections, matching the
existing player-side boundary without changing valid reducer-produced inputs.

Commands (`learned_command`, `best_skill_command`, `food_command`), live actions,
reservation acquisition, shared coordinator integration, schedulers, runtime
catalog activation, and account/UI behavior remain outside this slice.

Verified follow-on (base plus verified pure allocator): combined skill-focused
Release suite **2,029/2,029**, full Core Release regression **21,487/21,487**.
Compilation and tests used standard settings with no GC heap override. The new
928-vector corpus regenerates byte-for-byte, and every generated fixture file is
at most 92,231 bytes. No source/debugging retry was needed for this follow-on.
