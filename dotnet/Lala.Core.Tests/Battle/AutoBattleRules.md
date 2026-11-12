# Offline automatic battle rule chooser

`AutoBattleRuleChooser.Choose(context, actor, profile)` ports the retained Python
`wlre/services/battle/auto_battle.py::choose_action` into shared Core. It returns an
immutable `AutoBattleChoice` containing a detached `BattleCommandIntent`, typed
reason and original reason key/text, or an `InventoryPlanningError`. This is a
per-actor, offline source-parity feature, not an active automatic-battle service.

## Source behavior

Priority is dead ally, enemy HP, low HP, low SP, specified round, repeating action,
ordered actions, then normal-attack fallback. Thresholds are strict and absolute,
not percentages. Units are sorted by coordinates with stable ties. Missing HP
means neither living nor dead; a missing low-resource stat does not match.

The source's asymmetries are intentional: dead-rule eligibility excludes flying
units but its first revive target scan does not; conditional enemy HP uses
coordinate order; notice 2/3 selects local-role/master identities even on the
opposite side; low-resource targets use the first matching coordinates only for
items and support TargetKind 1/3/5. Metadata is checked before a next-skill upgrade.

Normal/catch target policy 2 still means ascending HP at this layer, whereas
learned/best-skill policy 2 delegates element selection. Repeat removes zero-ID
entries and uses Python modulo even for zero/negative rounds. Failed nonzero order
actions retain their target preference. An empty/disabled order list falls back
by coordinates rather than by HP. Only `ProtocolError` is suppressed. Reached
helper `KeyError` is returned immediately; invalid typed observations throw.

## Typed boundary

`AutoBattleProfile.PlayerDefaults` and `PartnerDefaults` match source defaults.
`AutoBattleProfiles.Normalize` validates IDs -3..65535, enum selectors and catalog
membership, forces recovery IDs -2/-3 to item kind, rejects item next-skill, and
pads initialized arrays to source limits (round 3, repeat 5, order 2) with zero
entries. The chooser invokes this validation. It does not parse permissive Python
JSON dictionaries, import partial rows, coerce booleans/numbers, or implement the
full settings/recovery/maintenance/party-guard schema.

Thresholds preserve Int64 integer versus finite nonnegative binary64 evidence;
comparisons do not first round Int64 HP/SP to double. Larger Python integers and
arbitrary dynamic input types are outside this typed API. Round is Int64, including
its minimum value. Explicit local role and actor identities, initialized equipment
and unit arrays, distinct source slot keys, and sparse stat/status dictionaries are
required. Slot aliases and coordinates remain distinct; no missing identity,
resource value, catalog row, or normal-attack data is fabricated.

Catalogs, player knowledge, inventory and units are caller-supplied unverified
observations. Empty catalogs retain the source's validation permissiveness and do
not imply authorization or trustworthy data. Per-actor repeated choices do not
account for one another's hypothetical costs. A caller must not treat allocations
as acquired holds or feed multiple such choices directly to a transport.

## Explicit exclusions

No AutoBattle start/tick/stop logic, enabled state, timer, scheduler, death/party
guard, persistence, runtime receive projection, UI, packets, live catalog
activation, command submission, reservation acquisition or new send authority is
added. Existing manual `BattleCommandPlanner.PlanRound` is unchanged. This API
neither checks nor claims an active round, and is not wired into `AccountRuntime`.
There is no whole-round automatic chooser in this change.

## Verification

`generate_auto_battle_vectors.py` invokes the actual retained Python validation,
chooser and lower-level command helpers against synthetic observations. It never
runs the scheduler or game network. The deterministic gzip fixture contains 1005
cases, eight reason paths, distinguishing flying-first revive and pre-upgrade target cases,
59 final ProtocolErrors and 19 reached KeyErrors, with
normalized source hashes and compressed/decoded hash checks. Every parity case
asserts input immutability. Directed contract tests add strict bounds, initialized
arrays, integer/binary64 comparisons, error short-circuiting, sparse evidence,
repeated hypothetical allocation behavior and public defaults. The separate
non-friend `Lala.Core.PublicContract.Check` constructs and runs a synthetic chooser
using only public APIs. These establish offline source parity, not live acceptance.

Regenerate from the repository root:

```
python3 dotnet/Lala.Core.Tests/Battle/generate_auto_battle_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj --filter FullyQualifiedName~AutoBattle
dotnet run --project dotnet/Lala.Core.PublicContract.Check/Lala.Core.PublicContract.Check.csproj
```
