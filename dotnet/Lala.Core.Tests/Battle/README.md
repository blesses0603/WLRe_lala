# Combat rules parity

`generate_combat_vectors.py` calls the retained Python `combat.normal_skill` and
`combat.effect_text` with explicitly synthetic, isolated catalog snapshots. It
produces 160 attack-selection fixtures and 288 effect-formatting fixtures. These
cover all weapon categories, transformed player bodies, human/monster companions,
all reviewed broken weapon IDs, rocket launchers, missing equipment/catalog rows,
foreign ownership, unknown NPC kinds and monster attack modes. Refusal messages
are compared as well as successful action IDs.

The C# core consumes copied, immutable typed snapshots. It does not invent NPC or
weapon data, load an unverified catalog, send attacks, run a battle AI, or calculate
absolute HP from damage deltas. The production resource loader/version checks and
server-authoritative HP snapshots remain separate migration work. Tests passing
prove parity for these two pure rules, not live battle acceptance.

Regenerate from repository root:

```sh
python dotnet/Lala.Core.Tests/Battle/generate_combat_vectors.py
```
