# Remaining combat knowledge receive state

This is the remaining receive-only part of
`wlre/services/items/combat_resources.py::apply_live`, together with
`resolve_equips` and the identity predicate in `profile_for`. It complements,
rather than replaces, `BagReceiveReducer` and `CompanionReceiveReducer`.

## Scope and ownership

`CombatKnowledgeReceiveReducer.Apply` takes an immutable player knowledge
snapshot, the current companion snapshot, the **pre-local-dispatch** battle
snapshot, one decoded server observation, the current nullable local role ID,
and an explicit optional `CombatKnowledgeCatalog`. It returns all three
replacement projections in `CombatKnowledgeReceiveResult`.

- `PlayerKnowledgeSnapshot` owns only `knowledge.player`. It does not own role
  identity, raw S8 `State.attributes`, inventory, or battle units. Its
  `Stats : ImmutableDictionary<string, long>` is the exact current numeric
  knowledge projection, suitable for later observers that run after
  `apply_live` but before local dispatch. Unknown stats are absent, not zero.
- `CompanionProfileSnapshot.Data` remains the original full S15 snapshot.
  Optional `EquipmentOverrides` is the current authoritative equipment when
  non-null; otherwise use `Data.Equips`. Battle and S8 stat replacements remain
  in its existing `StatOverrides`. Fresh S15 replacement clears the equipment
  override; existing companion logic handles same-NPC S8 replay and different
  NPC/delete buffer invalidation.
- `BattleUnitState.Layout` remains the original full received unit layout.
  `Equips` returns the current S11-252 appearance overlay or `Layout.Equips`.
  S11 changes preserve current HP/SP, attributes, exit flags and all battle
  metadata. A replacement unit/start resets the overlay through the existing
  battle reducer.
- Full equipment records retain their `ItemSave` under `OriginalRecord`;
  `ItemId`, present `DesignId`, and present `Damage` carry current values.
  An empty slot has only item ID zero. A sparse S11 replacement has only item ID
  and design ID, **not** stale damage/plugin/serial metadata. Original full
  companion/battle input remains separately available for historical inspection.
  Damage is UInt32 and can exceed the original ItemSave byte field.

The optional companion and battle properties preserve existing constructors and
old projection defaults. No AccountSession, lifecycle, UI, transport, or resource
activation behavior is changed. The subsequent [shared receive integration](../State/ServiceKnowledgeAllocationREADME.md)
composes this reducer in ServiceStateCoordinator.

## Composition contract

For one successfully decoded event, resolve this remaining knowledge slice
against the current role and pre-local battle state. Retain its returned player,
companion and battle snapshots, rather than keeping independent parallel copies.
Run the existing bag and `CompanionReceiveReducer.ApplyBeforeLocal` receive
slices exactly once as applicable; their handled branches are disjoint from the
new writes. Later pre-local observers can consume the resulting player stats.
Then dispatch the event to the existing local domains exactly once, using the
returned battle projection as input. Mirror local S8 companion-buffer writes
with the existing `ObserveLocalAttribute` composition and preserve the existing
S15 invalidation reconciliation between that buffer and local attributes.
The new reducer does not duplicate or reconcile either attribute buffer itself.

The player resolver runs at the start of **every** decoded event, even an
unrelated or inventory-handled event, before the Python inventory early return.
Failed packet decoding must not call any reducer, resolver, or observer. No
packet counter, session generation, login reset, or catalog refresh is inferred
here. On an explicit owning-state reset the caller supplies fresh Empty
snapshots; merely changing role context does not silently reset knowledge.

The dictionary of skill records also has `SkillOrder`, retaining Python first
insertion order (overwrite in place, remove, then append when re-added).
Removed skill IDs retain their source remove-and-append order. The companion
slice's existing order and raw S15 skill-slot metadata remain unchanged.

## Exact receive behavior

- S5-3 marks the player ready, replaces mapped skills and raw skill records,
  resets removed IDs, and merges all numeric stats without discarding earlier
  fields such as S8 `atk`. Unmapped keys and zero-level records remain in the
  raw records; no learned skill is invented. A zero mapping ID is ignored.
  Duplicate mapped IDs keep first insertion position and last positive record.
- S8 self updates preserve negative and zero values, overwrite only known stat
  names, and update/removal evidence without implying readiness. Other-player
  S8 remains unrelated even if its numeric role ID happens to equal local role.
  Companion S8 stays with the existing companion reducer.
- S5-47 records level, **degree 2**, and signed Int64 EXP. StarCore and the
  reserved point bytes do not become inferred stats.
- S23-11 replaces player equipment with nine empty slots plus mapped records;
  fit 11 maps to slot 7. Duplicate fits are last-wins. Unknown item rows retain
  full unresolved records; a present row with fit zero/invalid is known but
  unplaced. New snapshots clear old deferred updates and the resync latch.
- Late item mappings resolve pending rows in original order. Partial resolution
  can fill slots but defers all queued updates until every row is known. When
  all are resolved, replay is ordered and removes the deferred field (null),
  which differs from a known empty queue. Catalog selection alone does nothing.
- Damage/break events queue when player equipment is unresolved. At 256 queued
  events the **next** such update clears equips/unresolved/queue and latches
  `EquipmentNeedsSnapshot=true`. It does not accept guessed replacements until
  a fresh equipment snapshot. Companion fixed-slot equipment requires no
  catalog-driven pending queue.
- S11-252 with valid index 1..9 queues an unresolved own-player appearance
  **and** may immediately replace a changed item ID. Same item ID ignores the
  design update in a profile. Deferred replay replaces unconditionally, even
  for the same ID. Matching battle units always get the appearance/design,
  including other owners, independently of profile existence.
- Damage changes only damage. Broken equipment changes item ID and damage 250,
  preserving other full/sparse metadata. A missing explicit break slot uses
  the current item's fit map; unknown/invalid fits do nothing.
- Battle start/units copy only HP, SP, maxima, level and degree into the matched
  profile. Player PID wins first; a companion must match local master, slot,
  and NPC ID. S51 copies only kinds 25/26/46/47 from the current occupant, with
  no buffering for absent units. Battle max-stat attributes do not rewrite
  the original layout maxima. S50 never causes inferred damage/healing.
- Duplicates and late packets remain arrival-ordered. Empty starts clear battle
  units but do not erase previously confirmed profile stats. Unknown role
  cannot match; a known role ID of zero remains valid. Invalid equipment index
  events are ignored. Synthetic typed battle units with too-short equipment
  fail atomically if a matching valid equipment update would index past them;
  the wire battle layout always supplies nine slots.

## Evidence and verification

Run from the repository root:

```sh
WLRE_DISABLE_AUTO_CATALOG=1 python dotnet/Lala.Core.Tests/Inventory/generate_combat_knowledge_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~CombatKnowledge
```

The generator executes retained `apply_live` and actual receive decoders, plus
local battle/S8 reducers in source order. It uses only synthetic offline packets
and explicit unverified key/item/NPC mappings. There are **40 sequences and
1,646 checkpoints**, including 30 seeded mixed traces; every snapshot is checked
again after later transitions to prove immutable history. Strict malformed
packets leave publications unchanged; malformed S51 metadata is ignored by
local state while the top-level equipment resolver still runs. Missing/partial
catalogs, duplicate keys/fits, unknown roles, role changes, both 256-update
queues, signed/unsigned extremes, out-of-order/late records, equipment reset,
and companion identity reuse are covered.

Twelve additional contract tests cover original layout/full-record preservation,
current versus historical equipment, nullable presence, immutability, sparse
same-ID deferred replay, unknown/zero-fit distinction, known role-zero versus
unknown-role profile/equipment matching, short synthetic battle equipment atomic
failure after earlier candidate updates, and null arguments.
Fixtures use deterministic TestSupport gzip **byte literals**, not Base64 or
large string literals. Deterministic partial generated files are capped at
500,000 bytes each, partitioned only between complete sequences; `Sequences()`
retains the same case order and public API. Source hashes normalize only byte CRLF to LF; no text
re-encoding/BOM removal occurs.

## Remaining gaps

`learned`, `weapon_group`, `skill_reasons`, `target_valid`, learned/best-skill and
food commands, cost allocation, skill rows, field context, consumable actions,
reservations/sending, automatic battle, and catalog/runtime activation remain
outside this slice. In particular `Skills` reflects mapping at receipt, not the
source's later `learned` catalog-remapping helper; retained raw key/slot records
allow that future port without inventing evidence. No authorization follows
from readiness, skill mappings, equipment appearance, or current stats.

Integrated single-writer publication and observer ordering are covered by the
shared receive integration. Real resources, official-server acceptance,
platform/device testing and complete module parity remain separate gates.
Existing receive decoder/bag/companion tests remain part of the full Core
regression and are not replaced by these vectors.
