# Pure combat action candidates

`CombatResourceActionCandidates` ports the bounded, read-only selection logic of
`learned_command`, `best_skill_command`, and `food_command` from the retained
`wlre/services/items/combat_resources.py`. Its best-skill fallback includes only
`battle_commands.action_command(..., 'normal', ...)` and reuses the existing
`CombatRules.NormalSkill` implementation with a separately supplied normal-attack
catalog. It does not implement other action modes, ownership enumeration,
`catch_allowed`, or round planning.

These are **offline candidate intents**, not commands authorized for execution.
Allocations are the existing pure allocator's proposed cost rows. No reservation
is acquired, released or installed, no resource is consumed, and no packet is
constructed or sent. There is no session, AccountSession, scheduler, global
catalog, UI, Android, live-game or shared-coordinator dependency. Inputs and
results are detached immutable observations; readiness is never invented.

## Preserved behavior

- Current ownership and learned/equipment evidence are obtained from the existing
  `CombatResourceKnowledge.Learned` helper. The original two-hop learned-chain
  limit, current-level limit, removed/raw server evidence, equipment grants and
  stale companion slot identity checks are preserved. Only the final skill is
  validated, with the existing ordered `SkillReasons` diagnostics.
- Learned/food target filters use the caller's original battle dictionary keys.
  Normal fallback uses coordinate-derived keys, as the source does. Ordered entry
  arrays preserve insertion order for exact ties, and reject duplicate source keys
  rather than treating an unordered dictionary as source order.
- HP, element and coordinate tie ordering, learned normal-skill actor elements,
  generic-skill catalog elements, target-NPC restriction and target validity are
  unchanged. Normal fallback deliberately permits flying enemies, matching the
  source normal path rather than reusing learned-skill target restrictions.
- Best-skill candidates retain physical/magic classification, the player-only
  known ATK/MATK preference, SP/Sort/numeric-ID ordering and ProtocolError-only
  suppression. A reached malformed catalog field aborts with a source KeyError;
  it is not silently skipped in favor of another learned or normal action.
- Player item costs reuse `InventoryPlanning.Allocate`. Companions skip these
  costs. Inventory `UseFailed` remains a food gate, not an invented skill gate.
- Food retains ready/reliable/use-failed/war-style error precedence, field bypass
  of battle bans/restrict bit 256, living same-side targets, sparse stat defaults,
  numeric recovery-ratio priority, bag slot/item filters and available quantity.
  Locked, timed, alchemy, exclusive/uncertain and reserved rows use existing bag
  accounting. HP/SP detrimental attributes reject the item, while values 0 and
  100 do not. Duplicate effect attributes retain the existing last-value behavior.
  Any sufficient food beats undersized food, then absolute difference, numeric
  slot and item ID break ties.
- Food ratios use exact integer division rounded directly to binary64, retaining
  Python ties near 2^53 and Int64 limits. Casting numerator and denominator first
  is not equivalent. Missing-resource differences and food distances use
  BigInteger; descending HP avoids overflowing when negating Int64.MinValue.

## Typed boundary

Existing wire-domain IDs/slots, Int64 observed statistics/catalog integers, finite
binary64 element weights, explicit immutable collections and the exact food resource
keys `hp` and `sp` are supported. Missing reached skill fields and target statistics produce source
`KeyError` candidate errors, and source `ProtocolError` text remains intact.
Arbitrary malformed Python object types and numeric coercion are not a C# input
surface. In particular, other food resource strings (including uppercase names,
newlines and Unicode expansion characters such as ß) throw `ArgumentException`
with parameter `resource` before the source food gates run. Null throws
`ArgumentNullException`; it is not changed to `hp`. This is an explicit typed delta
from Python's permissive string input and exception formatting, not claimed
Python error-text parity. For `hp`/`sp`, source gates and their precedence remain
unchanged. UI, validated recovery settings and battle/AI choices produce only
these two keys, and `heal_effects` itself can only return HP/SP effects. Raw Python
command dictionaries may forward other strings, but those have no food effect.
Invalid typed imports (null/default collections, ambiguous order) are
rejected rather than repaired. Food imports must give the existing bag ItemOrder.

Normal fallback requires known actor and local-role wire identities because that
is the existing `CombatRules.NormalSkill` contract. Missing identities are rejected
as invalid typed input rather than assigning synthetic IDs to reproduce Python's
`None == None` behavior. Learned/food and the existing pure field knowledge APIs
retain their nullable identity semantics. This boundary does not authorize any
foreign actor, and the original helpers' absence of extra actor-liveness gates in
normal/food selection is not replaced with invented checks.

Catalog additions are only explicit item `Restrict`, the existing sparse actor
Stats-backed `Element` accessor, actor `ChangeBodyId`, and catalog
`ElementWeights`. Nothing loads, validates provenance
of, or activates these catalogs. Full module/runtime migration remains incomplete.

## Real-Python verification

`generate_combat_action_candidates.py` calls the actual retained Python functions,
with explicit synthetic pinned combat catalogs and a supplied normal snapshot.
It does not replace selection logic with a local reimplementation. It also checks
that Python leaves all input observations unchanged. Source fingerprints normalize
CRLF bytes to LF and make no other content changes.

The corpus retains **1,709** real-source observations: **1,649** in-domain exact
differential cases and **60** explicit unsupported-resource boundary cases. Cases
cover learned chains, appearance/equipment evidence,
stale/raw/removed ownership evidence, targeted/untargeted/dead/flying/missing-stat
selection, all target kinds and banned war styles, item holds and restrictions,
known/unknown player attack preference, malformed reached catalog fields and exact
numeric boundaries. There are 28 source KeyErrors and 1,148 ProtocolErrors. The
single deterministic gzip fixture is **106,428 bytes** (7,109,103 decoded bytes),
embedded as a named resource rather than C# syntax. The shared fixture helper
verifies both compressed/decoded hashes and bounds. Every input/output is checked
against Python for in-domain cases. The 60 unsupported-resource observations retain
their original Python results in the fixture, but tests explicitly assert typed
rejection instead of claiming their error text matches. Test classification is
also derived independently from the input kind/resource key, not just its fixture
flag. Retained input snapshots are rechecked after C# evaluation.
Contracts additionally retain earlier candidates across repeated calls, changed
reservation observations and revoked learning evidence.

```sh
PYTHONPATH=/tmp/daily-assistant-deps python dotnet/Lala.Core.Tests/Inventory/generate_combat_action_candidates.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~CombatActionCandidate
PYTHONPATH=/tmp/daily-assistant-deps python -m unittest tests.test_official_combat_catalog tests.test_official_normal_attacks tests.test_companion_sync_safety
```

Verification:

- Before the typed-resource follow-on, focused Release candidate suite:
  **1,720/1,720**; full Core Release regression: **26,027/26,027** against its exact
  compiled assembly (commit `ef09d3a`).
- The typed-resource follow-on passes **1,729/1,729** focused Release tests. It adds
  nine directed rejection contracts and explicitly classifies the 60 out-of-domain
  source observations. A new full run on this branch was not performed; integrated
  full regression is a separate gate after integration.
- Retained Python official-combat-catalog, normal-attack and companion-sync-safety
  regression modules: **19/19** using their supported unittest runner.
- Fixture regeneration is byte-for-byte stable, including its gzip header, and
  every new source fixture remains below 500 KB with either LF or CRLF endings.
- `git diff --check` passes. Compilation/tests used standard settings, without a
  GC limit or checked-in build-policy change. No C# compilation or test failure
  occurred. An initial pytest invocation was unavailable in this environment;
  the source modules' unittest runner above completed successfully.

Compiler and full Core regression runs were serialized with the other migration
work. Synthetic parity is not official-resource, device, live-server or complete
module acceptance.
