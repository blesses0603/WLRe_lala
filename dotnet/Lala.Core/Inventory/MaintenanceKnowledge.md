# Historical maintenance knowledge

`AccountRuntime.InspectMaintenance(repairBelow, repairItems)` captures one exact
`PublicationSnapshot` and calculates outside the runtime gate. The result retains
that basis, not a current-at-return guarantee. Missing running receive yields
`NoPublication`; missing current catalog yields `CatalogsUnavailable`. It never
substitutes a historical catalog after revocation. Stop, hold, replacement
session, disconnect, and disposal use the existing publication lifecycle.

The new algorithms port the bounded source decisions in
`wlre/services/items/maintenance.py` and `post_battle_maintenance.py`:

- Ordinary repair targets visit player equipment, then every matching active NPC
  profile in source insertion order, and equipment in slot order. Target NPC
  index comes from the source profile. The source broken-ID set and 25746 are
  excluded, then Special=0, FitType 1–6, instance lock/time flags, and strictly
  0 < damage < 250. Remaining durability 250-damage must be <= threshold.
- Sparse appearance replaces old metadata. Unknown damage never becomes zero or
  reuses the old full record. As in Python, absent sparse lock/time flags are
  false; a sparse row with subsequently known damage can qualify. An unknown
  active NPC ID is not a known zero. Catalog-reviewed Special/Kind/FitType must
  exist; the implementation does not infer them from an item identifier. New
  catalog binding alone does not resolve pending equipment: the next receive
  applies the existing reviewed fit projection, as Python apply_live does. This
  query reads published equipment rather than silently resolving an alternate copy.
- Repair stock requires ready/reliable bag observations, confirmed Kind=25 and
  Special=130, clear instance flags, known item rows, and source availability.
  Any nonzero reserved counter excludes the entire slot, not just reserved units.
  Alchemy, expedition, maintenance, exclusive and uncertain hold observations use
  the existing availability helper. Counts and output order follow source bag
  insertion order; the current count/damage override the original wire record.
- Source selection visits the two configured IDs in preference order and bag
  slots in numeric order. Full count must be available and source damage <250.
  Broken supplies may appear in stock but cannot be selected. Selection is exposed
  only if an eligible target exists. No reservation is acquired or released.
- Internal equipment lookup and cleanup restriction classification retain the
  source helper decisions. Cleanup prefers Sell when bit 16 is clear, otherwise
  Delete when bit 128 is clear. This is not a cleanup plan or an exposed command.

Options use threshold 0–249 and exactly two unsigned item IDs, with zero meaning
an empty preference. Unlike Python validate's permissive empty-catalog case,
nonzero configured IDs must have reviewed repair metadata here. Unknown metadata
is not a negative authoritative classification; invalid options are reported
without a candidate. Typed received snapshots cannot represent Python booleans
as integer damage, negative unsigned damage, or non-integer restriction values;
no new permissive conversion is added. Internal helper ordering assumes the
existing immutable receive reducers' matching order/key invariants.

No auto-repair/sell/delete, packets, timers, battle or field coordination, role
ownership check, pending-operation lifecycle, use-failure/settle gates, online
provenance, or runtime admission is added. `Evaluated` is not action eligibility
under the command wrapper. All result surfaces remain held/non-authorizing.

## Verification

`generate_maintenance_vectors.py` executes actual retained Python helpers and the
actual tick selection prefix with synthetic inputs; `repair_packet` is intercepted
before packet creation or hold acquisition. It covers ordering, thresholds,
exclusions, unknown fields, stock flags/counts, configured preference and all
reservation types. The generated C# fixture is deterministic and offline.

Framed loopback runtime tests exercise held catalog preparation, source-backed
receive observations, exact joins, revocation and retirement. Synthetic reviewed
rows explicitly test positive algorithms and sparse replacement without claiming
a reviewed positive resource payload. The existing synthetic trust seam verifies
wiring only. Public-contract checks reference the real public runtime entry and
prove inert inspection performs no acquisition or resource writes.
