# Optional dungeon and cooperative catalogs

This closes the data path used by Python `instance_runtime.build_catalog`, `instance_browser`,
and the instance catalog list: source IDs/variants, names, scene IDs, player and level limits,
time limits, room counts, awards, flags and cooperative event details. It does not change UI
widgets, create rooms, join, enter, start fights or run dungeon automation.

## One optional pair

`DungeonData_C` and `CooperateEventData_C` must both be present in the current DataPackage
manifest. The pipeline acquires only their roots and declared complete dependencies. Required,
skill, daily and instance data share download reservations and retained bundle bounds; verified
owned dependencies are reused and failed optional reservations are not refunded. Supported
optional acquisition follows Python priority: skill, instances, then daily definitions. Both raw
payloads must extract, parse and bind successfully before either enters inventory input. Unlike
Python’s per-table optional downloads, this bounded implementation plans the feature pair
atomically; it does not download one member when the other is absent from the manifest.

The new parsers follow the original binary layouts, including sixteen dungeon awards, both
award-slot bit sets, four cooperative followers and the follower reward. Binding uses this same
candidate's stage, text and item data. It rejects duplicate composite dungeon IDs, duplicate
normal-dungeon maps, missing scenes/names/items, invalid member ranges, malformed empty award
slots, and missing named cooperative events. All raw fields remain available in immutable rows.
Unknown availability stays unknown. `CreationSupported` describes the old catalog's structural
compatibility condition only, not current permission or an executable command.

The pair is persisted in the existing inventory transaction. Immutable-row conflicts or unknown
write outcomes still fail bootstrap. Independent opt-in readback reads both exact rows in the
same snapshot as required/skill/daily data and checks both recorded and recomputed SHA-256
against the owned prepared payloads. A missing or mismatched member drops the complete instance
feature; valid required and unrelated optional catalogs survive. Provider/cleanup/cancellation
failures remain fatal. Source versions/manifests are reobserved after preparation and readback.

All optional slots share the existing 160 MiB snapshot budget, while extraction shares the
existing 32 MiB aggregate table budget. Default readers and required matching stay ten-table-only.
Read-only refresh never repairs missing instance rows: an explicit successful bootstrap is needed
to add the pair to a prior inventory.

## Consumer boundary

`OfflineRuntimeCandidate.OptionalInstances` is a nullable immutable `InstanceCatalogPreview`.
It exposes entries and a set of declared kind-1 map IDs for read-only receive observations.
Null means unavailable. Catalog data does not authorize scene entry or room operations; all
existing session holds remain. No public factory can supply a manifest, trusted hash or claimed
resource authority. Other optional catalogs and image acquisition remain separate work.

## Evidence limits

Tests use generated UnityFS bundles, Python-derived binary/binder vectors and temporary SQLite
files. They retain existing required-table fixtures rather than importing official game data.
Successful offline catalog composition remains non-authorizing. No official network, account,
credential, real user database, Desktop UI or live-server acceptance is exercised.

Focused Release verification passed 3,029/3,029 cases without skips, including 859 Python parser/
binder parity vectors, required/optional acquisition, positive 12/14-table bootstrap/readback,
corruption isolation, cancellation/cleanup and retained daily/skill/readback regressions. The
initial run had two maximum-count test failures caused by immutable-array identity comparisons;
ordered sequence assertions corrected those tests without changing production code or expected
values, and the complete selection then passed. Independent static review found no blocker.
Both Python-derived vector generation and native fixture regeneration were deterministic; older
bundle fixtures remain unchanged. Full combined-head/platform verification is separate.

The integrated AccountRuntime also passes current normal-dungeon map IDs into
read-only receive observations through DeclaredMainCatalogMapIds. Missing catalogs
and revoked attempts receive an empty set. This does not activate room creation,
joining, entry, planning, or packet transmission. A white-box synthetic trust-bit
fixture verifies the actual receive projection and revocation; it does not prove
production trust establishment, official HTTP acquisition or live-server acceptance.
