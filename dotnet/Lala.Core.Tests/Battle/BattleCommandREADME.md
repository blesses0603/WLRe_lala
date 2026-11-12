# Offline battle action and round planning

`BattleCommandPlanner` ports the remaining pure selection surface from retained
`wlre/services/battle/battle_commands.py`: `slot`, `identity`, `owned_units`,
`catch_allowed`, all seven `action_command` modes, and `plan_round`.

These are detached **offline intents**, not executable game commands. No packet
is created, no hold is installed, no item or HP/SP is consumed, and no session,
transport, scheduler, UI, live catalog or AccountSession API is changed. Shared
round costs exist only in a private immutable inventory proposal during that call.
Successful plans return only immutable intents; failed plans return no partial
intents or provisional inventory. A later call starts from the caller's unchanged
observations, not an earlier proposal.

## Selection and error behavior

- Ownership requires a known local role and either the actor PID or master ID to
  match it. Living selection requires observed positive HP and no exit marker.
  Missing HP remains unknown and is not upgraded to liveness. Local-role actors
  precede companions, followed by column and row. Exact ties preserve source
  entry order. Nonliving enumeration includes dead and exited owned units.
- Slot strings derive from coordinates with invariant formatting; source battle
  dictionary keys remain separately retained. Commanded/excluded round slots and
  normal/capture target overrides use coordinate strings. Learned skills use the
  existing source-key filtering. Healing action modes intentionally do not forward
  the optional target override, matching Python's action dispatcher.
- Capture requires a catchable NPC, no already-owned NPC of that PID (even dead or
  exited), both required level observations, and at least six actor equipment
  entries. An owned companion uses its master's observed level and degree even
  if that master is dead, but uses its own sixth equipment item/net bonus. Missing
  masters or levels fail closed. Degree times 100, level, bonus and the additional
  five levels are calculated with BigInteger to preserve Python arithmetic across
  all supported Int64 inputs. Capture checks all eligible enemies before applying
  the target-slot filter. Capture/normal permit flying targets as Python does.
- Normal selection is the same implementation used by the existing best-skill
  fallback: `CombatResourceActionCandidates.Normal` and `BestSkill` share one
  extracted private `NormalCore`. It still calls `CombatRules.NormalSkill` and
  does not run learned-skill selection or invent an actor-liveness gate.
- Auto-skill and food delegate to `CombatResourceActionCandidates` unchanged.
  Existing skill provenance, malformed-field errors, inventory readiness,
  restrictions, availability, target ordering and reservation proposals remain
  their responsibility. Defend/escape always use target zero and their confirmed
  skill constants; capture uses skill 10008.
- Round readiness is checked first. Already-commanded and explicitly excluded
  actors are skipped before their modes are evaluated. Each successful intent's
  proposed costs are added to a new Reserved map for the next actor; caller-held
  reservations, exclusive holds and source bag order remain intact. Food proposals
  do not heal a hypothetical target or change later target stats.
- The first source ProtocolError terminates the round and gains the actor's name
  (including an explicitly empty name), or its slot when a name is absent. Source
  KeyErrors returned by resource candidates terminate without an actor prefix.
  Unknown action modes retain their source error and precede resource gates.

## Explicit typed boundaries

The existing immutable combat-resource, normal-catalog and inventory contracts
are reused. Wire IDs are UInt32/UInt16, coordinates are Int32, observed integer
stats and net bonuses are Int64, and reservation sums remain BigInteger. Python
integers outside these import domains, arbitrary object/string numeric coercion,
truthy non-Boolean markers and malformed dictionary objects are not C# inputs.
Typed capture catalog rows explicitly provide Boolean catchability and numeric
net bonuses; they do not load or validate official resources.

Identity requires a known actor PID. A missing PID in identity, a reached owned
actor ordering key, defend/escape/capture actor identity, or reached capture target
identity is rejected with ArgumentException rather than manufacturing an ID or
claiming Python KeyError parity. A missing local role yields no owned units;
reached capture requiring that role rejects invalid input. The shared normal
helper retains its prior requirement for known actor and local identities when
normal resolution is reached. The general Learned/Food/BestSkill helpers retain
their existing nullable identity behavior, but the new battle adapter rejects any successful candidate
with no actor PID at emission. Earlier candidate errors retain precedence; no
nullable identity is copied into a battle intent. The new BattleCommandIntent
therefore requires UInt32 ActorPid. For missing-ID malformed inputs, this is a
specified typed rejection rather than a claim to match Python's KeyError or its
earlier direct dictionary accesses. These restrictions do not confer ownership
or send authority.

Nullable MasterId denotes absent master evidence and Identity returns the source
missing-key default zero. Explicit Python `master_id=None` is not a separate
import state. Nullable Name denotes an absent name, not a source key explicitly
set to None. Missing source coordinates and arbitrary non-string names are also
outside the typed import surface. Empty names remain distinct and tested.
Default/null immutable collections, null rows and ambiguous source-key ordering
are invalid imports, not guessed or repaired. The readiness/unknown-mode source
short circuits are preserved before deeper inputs are inspected. These typed
limits are not presented as exact malformed-object parity.

## Real-source verification

`generate_battle_command_vectors.py` invokes the actual retained Python functions,
with explicit synthetic combat catalogs and inventory naming. It deep-compares
all source observations after each call, so an oracle-side mutation fails
fixture generation. Seven actual dependency source hashes normalize CRLF bytes
to LF and nothing else. The single gzip embedded resource uses an empty filename
and mtime zero and is verified for compressed/decoded SHA-256 and size bounds.
No C# base64 or large generated syntax is added.

The corpus currently contains 956 retained-source observations: 949 exact
in-domain differential cases and seven explicit typed identity/import rejection
cases retaining their original Python results. Tests derive the rejection class
from the actual input as well as checking its fixture label. It includes all
modes, source-key/coordinate distinctions, sparse liveness/level evidence, stable
ownership ordering, duplicate/dead/exited ownership, numeric capture boundaries,
shared skill/HP-food/SP-food round costs, existing huge reservations, later-actor
failure, exclusions, protocol error precedence and unprefixed malformed-field
errors. All typed C# input snapshots are also rechecked after evaluation.

Nineteen directed contract cases additionally exercise old-result immutability, repeat
calls, changed reservations, no partial failed plans, unchanged observed HP,
exclusion-before-validation, missing identity/order imports, heal/auto-skill emission identity rejection,
preceding resource-error preservation and invariant slot
formatting. Existing action-candidate tests cover the extracted normal helper's
best-skill fallback behavior without duplicating it.

```sh
PYTHONPATH=/tmp/daily-assistant-deps python dotnet/Lala.Core.Tests/Battle/generate_battle_command_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter 'FullyQualifiedName~BattleCommand|FullyQualifiedName~CombatActionCandidate'
PYTHONPATH=/tmp/daily-assistant-deps python -m unittest tests.test_official_combat_catalog tests.test_official_normal_attacks tests.test_companion_sync_safety
```

Synthetic parity is not live-resource/device/server acceptance or full runtime
migration. Integration, dispatch, reservation acquisition and battle scheduling
remain separate, unimplemented migration work.

Verification before the identity-emission review follow-up:

- Standard Release focused suite: **2,689/2,689 passed**, comprising 960 new
  battle-command tests and all 1,729 existing action-candidate tests. Compilation
  completed with no warnings/errors and no build-policy/GC overrides.
- The first focused run found a test-only snapshot serializer unable to encode
  BigInteger dictionary keys. It failed before planner evaluation; an exact
  integer converter fixed the harness, and the complete focused run above passed.
- Retained Python catalog/normal-attack/companion-safety regressions: **19/19**.
- Deterministic regeneration reproduced both fixture and generated C# hashes.
  Fixture: **57,346 compressed bytes**, **3,738,102 decoded bytes**. New text
  sources are each below 500,000 bytes with either LF or CRLF line endings.
- `git diff --check` passes. Full integrated Core regression remains the parent
  integration gate; a focused pass is not a full-suite or runtime acceptance claim.


Identity-emission review follow-up adds nine source observations (three explicit
missing-ID emission rejections and six preserved earlier food errors), plus seven
directed contract cases. It does not change general resource helper contracts.
Name=null still represents absent name evidence, not explicit Python name=None;
empty names remain supported. The new one-actor ownership contract also exposed
LINQ's permitted omission of sort-key evaluation for singleton sequences. Identity
validation now occurs before sorting, matching Python's reached-key requirement;
a direct retained-Python check confirms its missing-PID KeyError for both living
and nonliving singleton enumeration.

The final standard Release focused rerun passes **2,705/2,705**, comprising 976
battle-command tests and all 1,729 unchanged action-candidate tests. The first
follow-up run was 2,703 passed / 1 failed on that singleton import guard; the final
run includes its correction and dedicated regression. Retained Python regressions
again pass **19/19**. The updated fixture is **57,840 compressed bytes** and
**3,768,801 decoded bytes**, with byte-identical regeneration and unchanged source
fingerprints. Whitespace and LF/CRLF file-size checks pass. The parent still owns
full integrated regression and runtime acceptance remains outside this scope.
