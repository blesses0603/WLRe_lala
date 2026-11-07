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

Not included: `skill_reasons`, `skill_rows`, `learned_command`, `best_skill_command`,
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
