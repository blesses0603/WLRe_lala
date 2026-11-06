# Navigation database: verified subset, preview only

2026-11-06 follow-up to [bounded extraction research](OFFICIAL_NAVIGATION_RESEARCH.md).
This is a partial migration. All three navigation seeds remain required by existing
live movement/UI consumers; this change does not replace those consumers or enable
new movement packets. The shared database preview consumer and CLI run on desktop
and Android Python cores. Android device/APK/UI acceptance has not been performed.

## Current scope (phase 25)

Player houses only require entry and exit. House interior navigation, furniture
placement and obstacle rescans are excluded and are no longer migration completion
criteria. Navigation requests reject logical templates 10000/10298/10299 and
dynamic IDs 63501–65500; direct preview/sync also rejects models 10000/10004/10005
before fetching. Instance IDs 61501–62000 are not houses and remain in scope.
The existing tent enter C65-1 and leave C20-8 flows remain separate, including
current official exit-door resolution and server-confirmation checks. Coordinate
projection and non-navigation house features are unchanged.

The three seeds cannot yet be deleted: the old stage table still contains 1,832
non-house rows referencing 971 models; origins contains 724 entries and the
navigation archive contains 724 decoded models (763 catalog rows total). Current
official DB preview evidence covers six general-map models, plus three historical
house samples now excluded. These counts are coverage evidence, not proof that
every old model remains current. General-map movement still needs broader
version-matched geometry coverage and traversal/smoothing verification.

## Implemented

`navigation_sync.sync_model` obtains one selected reviewed model from the current
verified MainPackage manifest, checks the official version before and after, and
fetches at most two complete bundles totalling 32 MiB. This ceiling includes cached
bundle sizes and is deliberately conservative. No full-scene dependency loader is
modified. The dependency name is only a candidate: membership in the manifest and
an exact serialized CAB/path-ID TextAsset reference are mandatory. Both bundles
must pass size, MD5 and CRC verification. There is no fallback to an arbitrary URL,
partial bundle or another version after failure.

`astar_cache` recognizes only nine reviewed cache SHA-256 fingerprints and A* 4.3.60.
It validates all archive members, geometry counts, vertex indices, exact binary
consumption and the graph-space transform. The new reader also validates the node
reference map and directed connections, including the declared triangle edge.
Unknown versions/layouts/models fail closed, retaining the original bundle bytes.

`navigation_database` stores preserved cache bytes, normalized geometry/origin/
connections, provenance, attempts and an exact-version active pointer in SQLite.
Validation precedes the activation transaction. A failed transaction or download
retains the previous snapshot; reading requires the requested version and rechecks
both original digest and normalized contents. Earlier versions are retained but
never silently selected for a newer runtime. Database schema 1 is explicit; an
unknown schema is rejected without overwriting it.

`navigation_preview.PreviewRepository` reads this database, applies serialized
connection direction and native walkability bit zero, and converts packet XY
using the current official stage rows. Coordinate formulas are restricted to the
reviewed complete catalog identity. The route now uses the reviewed default serialized costs; see
[dynamic navigation progress](OFFICIAL_DYNAMIC_NAVIGATION.md) for the supported
cost policy, planar smoothing and product UI entry points.
It always reports `can_send_packets=false`. No existing live-movement path is
switched to it. Player-house navigation is excluded by product scope, including
verified floor contexts; entering and leaving the tent remain supported.

Run after core official data preparation:

```console
python -m tools.preview_official_navigation --map 10001 --sync
python -m tools.preview_official_navigation --map 10001
```

`--sync` is explicit and per model, not an automatic startup download. Omitting it
reads the exact-version DB only. The CLI verifies the current official core runtime
before using the preview. This distinction is intentional until broader navigation
and live routing acceptance is complete.

## Expanded actual evidence

| Model | Nodes | Directed connections | Purpose |
| --- | ---: | ---: | --- |
| 10001 | 282 | 806 | Ordinary scene |
| 12600 | 513 | 1,494 | Ordinary scene |
| 10000 | 36 | 90 | Largest furniture-house template |
| 10004 | 32 | 80 | Middle furniture-house template |
| 10005 | 36 | 92 | Small furniture-house template |
| 58001 | 4,071 | 11,726 | Large world map |

For all six, the serialized connections agree with geometric shared edges and the
serialized edge numbers match their triangle endpoints. This is not an assumption
that every future graph must be symmetric or geometrically adjacent: unsupported
connections are rejected, and a synthetic directed graph test forbids reverse travel.

Official native reader evidence adds MeshNode.DeserializeReferences `0x2d94e30`:
Int32 connection count, Int32 node reference, UInt32 cost and Byte shape edge for
this version. GraphSerializationContext.DeserializeNodeReference `0x22c6730`
resolves through the reference map. AstarSerializer.DeserializeNodeReferenceMap
`0x22ca4e4` reads maximum node index plus the serialized graph-node enumeration.
GraphNode.get_Walkable `0x2d83808` reads bit zero; DeserializeNode `0x2d94308`
preserves that bit. No original game code was executed during this analysis.

Stage.GetStageId selects furniture templates using Room.floorSize[Room.floorIndex].
Current official stage IDs 10299, 10298 and 10000 map to models 10005, 10004 and
10000 respectively. Consequently a missing bundle named 10298/10299 is not missing
official house data: those are logical IDs, not the models to download.

Comparing 1,337 current official stage rows with 1,836 old coordinate entries found
one new stage, 500 old synthesized instance IDs absent from the official table,
and 13 changed model/dimension rows. Twelve of those have changed map-height
inversion values. The 500 IDs (61501–62000) are in the instance-reserved range and require verified instance aliases, not house-floor assumptions. Player houses occupy 63501–65500.
This is why the legacy coordinate seed cannot yet be deleted as a safe migration.

## Remaining work and validation limits

* Other navigation caches still need source/format coverage; six fingerprints do
  not establish support for every scene, multiple tiles, rotated graphs or links.
* Resolve live room floor size/index and organization-instance aliases from current
  session state before mapping dynamic IDs. Test changing floors during a request.
* Validate traversal tags/cost policy and runtime obstacles, then integrate the
  product UI and movement consumers with snapshot pinning and cancellation.
* Only after those consumers and cold-start cases are covered can the three seeds
  be removed. No new seed has been bundled, and no existing seed was removed here.

Automated synthetic tests cover exact-version selection, empty cold start, malformed
geometry/references, directed edges, unwalkable nodes, quota rejection before fetching,
version changes during download, normalized/raw corruption, transaction rollback,
old snapshots, unsupported schema, unknown houses and no movement authorization.
Actual official files are retained privately for source-chain/database checks and
are not shipped as fixtures. These checks do not constitute live-server or real-device
movement acceptance. Changes remain local; there is no new remote CI result.

Validation for this local stage: 18 synthetic tests pass on each host Python
environment. All six official samples completed verified source extraction, atomic
import and database preview on desktop; Android's Python core independently read
and validated the same six database snapshots. This is host validation, not APK
or device execution. Repository documentation audit also passed.

## Phase 23: nine models, verified house context and traversal tags

The reviewed model set now additionally contains 12050 (844 nodes / 2,488 arcs),
13216 (81 / 220) and 11139 (605 / 1,772). They cover changed scene dimensions and
a model used by new logical stage 15138. This research batch fetched 5,960,481
bytes under the unchanged 32 MiB cap. All three completed the real source-chain
verification, database import and readback. The whitelist remains finite; this is
not evidence for all remaining models.

Correction to the earlier investigation: the 500 missing old coordinate IDs are
61501–62000, in the **instance** reserved range, not player houses. Official
Define.lua sets dmMinSceneNum=61501 and house bounds to 63501–65500. This correction
is reflected in the stage-comparison discussion above; no mapping was activated
from the mistaken house interpretation.

Verified current Stage.ReceiveChangeMap (S7-1/S12-1) carries optional floor and
size information. `house_navigation` recognizes only the observed reader's bounded
extension layouts (1, 3 or 5 bytes), preserves an unverified result for other
layouts, and does not infer a floor from empty S62-64. Only local-player position
snapshots update navigation's context. Sizes are scoped to one house and discarded
on an unknown extension, a different house, or leaving the house. The actual floor
must have an explicitly observed size; client defaults are not substituted for a
missing observation. Preview mapping uses the current official template stage and
rejects a stale navigation state. Dynamic room context is not written into the
static resource DB.

Room.SetFurnitureAppear selects objects by active floor and normal use state,
then uses FurnitureData.GetModelName and TransferFurniturePosition. Room's removal
and pillar handlers call AstarPath.active:Scan after changes. Therefore a pristine
house cache is not a verified populated-house obstacle map. The existing stale
geometry guard remains in force. Collider/prefab source extraction, rotations,
use-state toggles, pillar models and the Recast rescan have not been reproduced.
These are concrete blockers to enabling live house movement from the new DB.

Additional verified traversal evidence:

* MoveController.New sets Seeker.traversableTags to TrafficPathTags.Land and adds
  a FunnelModifier. Define.lua specifies masks land=9, sea=4, sky=15.
* Native GraphNode.get_Tag at 0x2d93f7c extracts five bits starting at bit 19.
* Role.CheckCanArrivePos passes the active seeker's mask to LuaHelper.GetPath.

PreviewMesh now filters both walkability and those explicit travel-mode tag masks.
Its default is land; the CLI accepts `--travel-mode land|sea|sky`. This is an
explicit preview selection, not an assertion about the live character's vehicle
or capabilities. Unknown modes are rejected. Geometric costs and edge midpoints
still do not emulate the client's serialized costs and FunnelModifier. Routes
continue to report no packet authorization, and the formal UI/movement consumers
remain on their existing path pending the missing dynamic semantics.

Source artifacts were fetched from the same verified official Lua index, MD5
checked, decrypted, and round-trip verified privately. Ciphertext SHA-256:

| Source | SHA-256 |
| --- | --- |
| Room.lua | 0e761261f506422fbcf4e566108a40e9fdc2090bc60fbad7f4047648c27a4b9d |
| Protocols_062.lua | 4498cabfb3ecb3a1e68e5f56918627ccceefc1ebacfaf2db564fc167e4c2b4d0 |
| Protocols_065.lua | 7e1e0e99cce318997a952cfabdb6fa00ff4c1643102021012d6e4ef3c454c260 |
| Role.lua | 08bfc2d875172effde41c9e0b5c65da1762eca064c4e8e3b9d25bf5b99085657 |
| MoveController.lua | 838d838df641f2c9c2b457a758c99b8387b12de9727176ff49a4623f98be3dc8 |
| FurnitureData.lua | 24670ae4691e3f4cdd172f790aa0d0f34ccaf652a311dd930f107c90daf7e915 |

No decoded source or key material is bundled. All three navigation seeds remain.


The instance alias gap was subsequently resolved for the reviewed catalog:
Data.OnLoadSceneData allocates aliases sequentially from 61501 in binary record
order whenever isDupMis is nonzero, repeating dupRoomCount times. The existing
normalized-resource encoding preserves dictionary insertion order; the preview
also requires the exact reviewed order fingerprint before deriving aliases. All
500 reconstructed current aliases (61501–62000) match the old model/dimension
mappings. Sorting rows before allocation is explicitly rejected. This is runtime
derivation from official table rows, not a shipped static alias table.
Data.lua ciphertext SHA-256:
`4582b74c53292dfe27e0eb60a0a065e7407f6ba2bfef56e264834f501a08490a`.

Phase-23 validation: full desktop regression passed 1,778 tests (3 skipped);
Android's isolated host regression passed 190 files / 1,456 tests (4 skipped).
The final alias addition and all navigation/floor cases then passed the targeted
27-test suite on both hosts. Android read and validated all nine actual database
models. These results do not include APK/device execution or live movement.
