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
official DB preview evidence covers seventeen general-map models, plus three historical
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

`astar_cache` recognizes only twenty reviewed cache SHA-256 fingerprints and A* 4.3.60.
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

## General-map coverage expansion (phase 26)

Official 1.3.23 MainPackage 1296 adds reviewed models 13217–13227, all from the
current stage rows whose dimensions differ from the legacy table. Together with
previous 12050/13216 and new logical map 15138 (model 11139), all fourteen
new/changed stage rows now have a reviewed current geometry model. This does not
mean the rest of the legacy archive has been validated against the current release.

The eleven models required 9,911,919 bytes across 22 whole manifest-verified
bundles. Each extraction resolves the exact serialized CAB/path-ID pointer. All
passed strict archive, triangle, reference, directed-edge, tag and coordinate
checks; paired vertex transform residual is zero for this batch. No bundle or
game content is committed. Exact cache fingerprints are the only new reader
allowances; malformed/unknown layouts remain rejected. Actual version-checked
`sync_model` imports succeeded for all eleven models. Desktop and Android host
readers produced identical results for 388 sampled planar smoothed routes. Each
retained the serialized route cost, stayed within the triangle corridor, and was
no longer than the midpoint baseline. These are sample checks, not exhaustive
endpoint coverage or official-client movement traces.

| Model | Nodes | Directed arcs | Cache SHA-256 |
| --- | ---: | ---: | --- |
| 13217 | 146 | 404 | `a728cd68b449c76d89585bcb2f8c29a7bdd146e5da18d9ad01f6647565e689e6` |
| 13218 | 360 | 1012 | `ab622995a92f4bc8f6914c716fda0a82bc2bbfc52a3b6636e616c30d25485889` |
| 13219 | 420 | 1200 | `5fb34818dba90dd16c133f2504fd4e3a6da1351eb90262bab538da87b8de61cb` |
| 13220 | 375 | 1068 | `721540e7699eaa738ef8bf899bf2deb9b808fc11cf05c2678efbbf82b003337d` |
| 13221 | 212 | 590 | `13c46904d5c16e3418f4c2dd7a7ab24621323b8eccad677900c3031c9c3edc3f` |
| 13222 | 267 | 758 | `4899fcbe081b3f8924219ef26b4ae490afc007c38d85fb9b1b96d7a7dd38f1b9` |
| 13223 | 232 | 650 | `2bc5d749067948ad630697f71da34d9a79164ca7f8783625a1341b14be3bc455` |
| 13224 | 85 | 232 | `493c40032453791d503112d95dfc5ab87a5aa9674ba5be50b60122b7abe8b552` |
| 13225 | 188 | 526 | `713401e696f3befe979e17db6e0182bbcd20822e02cae187dfa83feabc5b10e1` |
| 13226 | 250 | 702 | `bd4581bbc2c1661123cd16e46303f0d9e8da63afea47330a50e38fce0b128828` |
| 13227 | 144 | 404 | `d95005692c09067a3ca6e5d32759d4ed002baec095535a4f7bc592f141a8ae90` |

`obstacle_scope` now reads the active official stage table when available, including
reviewed instance aliases. It does not cache that table across runtime revisions.
Unknown IDs/order or a failed official synchronization remain conservative; no
stale bundled table is consulted in those cases. The historical pre-sync path
still uses the stage seed, so that seed is not yet removable. House templates and
dynamic house IDs remain explicitly classified as houses regardless of runtime.

Remaining activation conditions: current-model coverage beyond this sample;
nonplanar funnel/endpoint selection parity; and a verified connection between
local actor travel state and the active Seeker mask. Official Role.CheckCanArrivePos
uses the actor's `seeker.traversableTags`, while MoveController initializes Land.
A user-selected preview travel mode is not sufficient movement authority. No
current official-client endpoint/path/packet comparison or live server acceptance
was performed. The existing formal movement remains on its legacy checked path;
preview routes continue to carry `can_send_packets=false`. Removing all three
seeds now would disable uncovered general-map features and is not safe.

Further source check: official index-verified TrafficController.lua (ciphertext
SHA-256 `4cefd6b037f2e6c32e8188aaca5dfee6617aa448b7d0bf943e481712e425748b`)
and TrafficToolData.lua (`218f3419e4b9d8d2c337093eaa0d4fd01ffd5383b950c40ec2116b8d555faa1c`)
were decoded locally. Neither supplied the missing Seeker mask assignment; this
is not evidence that the assignment does not exist elsewhere. The next concrete
check is native LuaHelper.GetPath / actor movement initialization, paired with
reference paths for slope and multiple-height endpoints. No authentication or
network policy denial occurred during this phase.

## Native path pipeline and full manifest inventory (phase 27)

Read-only analysis of the previously verified official ARM64 `libil2cpp.so`
(SHA-256 `7798c9aaa6986ee200deacf9816a5d2f17a606944aa4a56dd06bfa1acb344636`)
and metadata (SHA-256 `5a71da3a4b37486b056b9873655e42d7d7a583eae6ebfe2efdd18ebe66a23260`)
resolved these calls by image method tokens and ELF relocation-backed method tables:

- `LuaHelper.GetPath` at `0x31059f8`: constructs ABPath (`0x234c2f4`), writes
  its caller-supplied mask at path offset `0xac`, calls AstarPath.StartPath
  (`0x1a7a2bc`) and BlockUntilCalculated (`0x1a79d38`), then returns the path.
- `StartPathImmediately` at `0x310587c`: cancels the Seeker's prior request,
  constructs ABPath, copies the Seeker mask from offset `0x30` to path `0xac`,
  calculates synchronously, and calls Seeker.RunModifiers (`0x2a8e6a0`) with
  pass value 2 before its callback. GetPath does not make this modifier call.
- MoveController.MoveToPosition selects StartPathImmediately for the player,
  StartPath for other actors, and removes the first vector point when there are
  multiple points. Initialization explicitly sets the Seeker Land mask and adds
  or retrieves FunnelModifier. This does not prove the mask stays Land throughout
  every later traffic state; no new actor-mode authority is inferred.
- FunnelModifier's constructor at `0x24cda58` writes true at offset `0x2c`.
  Metadata identifies its fields as quality, unwrap, splitAtEveryPortal and
  accountForGridPenalties. Funnel.UnwrapHelper at `0x2358620` tests collinearity,
  projects vectors around a portal edge, calls Quaternion.FromToRotation at
  `0x30c70e0`, and applies Quaternion multiplication at `0x30c66a4`.
  These calls confirm a 3-D unfolding operation; they do not establish complete
  equivalence for a replacement implementation, degeneracies or endpoint rules.

No native client code was executed and no reference client path outputs were
obtained. Read-only disassembly and decoded Lua remain outside Git. Flat preview
smoothing is unchanged; slopes are still rejected when smoothing is requested.

`python -m tools.audit_official_navigation_coverage` now reports candidate source
coverage without downloading scene bundles or authorizing movement. It checks the
manifest package/version and SHA against the prepared runtime, excludes house IDs
and models, checks exact scene asset uniqueness and declared candidate dependency,
and reports whether the two complete bundles fit the existing limit. A candidate
is explicitly **not** proof of a valid cache pointer or graph. Synthetic checks
cover ambiguous/missing assets, undeclared dependencies, limits, stale manifests
and corruption. The tool may check current official versions during core runtime
preparation; it does not itself fetch scene bundles.

The reviewed 1.3.23 identity yields 1,333 non-house source stage rows and 972 unique
models: 770 have a unique candidate pair within the existing per-model budget,
and 202 have no unique matching scene asset under the reviewed lookup. Seventeen
models have reviewed cache fingerprints. This inventory covers source rows, not
expanded generated instance aliases; it does not assert that unmatched models are
unavailable from every other official resource path. Desktop and Android reports
are identical.

Actual DB route sampling across the seventeen general models produced identical
host results: 520 successful planar routes, 33 rejected nonhorizontal corridors,
and 35 paths rejected by serialized connectivity/tags. Added synthetic regression
checks prove sloped previews cannot activate Movement or emit packets, sea cannot
traverse a land-only fixture, and overlapping levels require height evidence.
Both hosts passed 26 targeted navigation tests; desktop UI/tent regressions passed
21 tests and Android navigation UI passed its test. These checks supplement the
phase-26 full suites (1,798 desktop / 1,476 Android), which were not rerun for this
read-only tool and test/documentation-only phase. No APK/device/live acceptance is
claimed. All three seeds remain; safe replacement still requires broader current
cache validation and actual movement-pipeline equivalence.

## Official ARM64 math vectors (phase 28)

The FromToRotation wrapper in libil2cpp resolves an engine internal call, so its
wrapper alone is not a complete math oracle. The same pinned official APK was
read using bounded HTTP ranges with its recorded ETag/size. ZIP CRC verification
produced `libunity.so`, 25,765,728 bytes, SHA-256
`dab8b8d67f215b8f8c83870a3ef4b118e5a0e0e2c225eb1f48e23ba9f1bc582c`.
Total research transfer was 10,434,855 bytes; the existing 32 MiB research cap was
not increased. Neither library nor downloaded game data is committed.

The Unity registration loop at `0x20bf38–0x20bf54` pairs the string array at
`0x18004f8` with the function array at `0x18069c8`, for 3,226 entries. Index 241 is
`UnityEngine.Quaternion::FromToRotation_Injected`, mapped to `0x17b6a4`, calling
`0xb493e4`. The latter normalizes nontrivial inputs and calls the matrix/rotation
helpers at `0xb51c0c` and `0xb48e7c`. This mapping is established from registration,
not inferred solely from a plausible function's output.

`tools.review_navigation_rotation` is an optional offline research tool requiring
Unicorn 2.1.4 and pyelftools in a separate research environment. It accepts only
the reviewed library SHA-256 values and size limit. Official ARM64 instructions
execute in virtual CPU memory, never as host code. FromToRotation execution has
an explicit instruction-address allowlist and a 2,048-instruction ceiling; the
pure quaternion/vector multiply has a 128-instruction ceiling and only its own
164 code bytes mapped. A nonreturning or unexpected path fails. There are no
system-call hooks, network requests or game-server operations.

Run with the independently verified libraries, keeping output outside the repo:

```console
python -m tools.review_navigation_rotation --libunity /path/to/libunity.so --libil2cpp /path/to/libil2cpp.so
```

The tool generated 136 official FromToRotation outputs (including opposite,
nearly parallel and zero inputs) and 268 official quaternion/vector multiplication
outputs. The combined official rotation direction error was at most approximately
6.25e-7 for these normalized test inputs; comparison of multiply against the double
precision formula differed by at most 2.34e-5 for the selected vectors. All 404
ARM64 outputs match exactly between desktop and Android Python hosts. Host-side
double-precision normalization/error reports can differ at their last decimal
bits between Python versions; these are not different official float32 outputs.
This is **pure-math emulation**, not full Unity/IL2CPP initialization, complete
Funnel output, Android device execution or live movement acceptance.

Route sampling was extended over the seventeen verified general models and all
three preview masks: land 520 accepted / 68 rejected, sea 36 / 0, sky 566 / 22.
Models with no eligible sea nodes contribute no sea routes; these counts do not
claim water coverage on every map. Both host results are identical. No new model
fingerprints or movement authorization were added in this phase. Both hosts pass
28 focused tests, including oracle input/hash/size rejection and existing
nonplanar movement guards. Application runtime code is unchanged; the previously
recorded full suites and UI checks were not repeated for this research-tool phase.

### Evidence still needed for nonplanar activation

Math vectors do not resolve Funnel.Unwrap's accumulated portal transformations,
portal repair, endpoint projection, Seeker modifier order/settings, or nearest-node
constraints for all actor modes. The next oracle must compare complete ordered
`vectorPath` results from the official pipeline. A minimal useful reference case
contains the exact official graph digest/version; start/end world XYZ; actual
Seeker mask and modifier settings; ordered node/portal identifiers; vectorPath
before and after modifiers; and complete/error status. Include slope, folded
corridor, near-collinear portal, overlapping levels, and a non-Land case.

These can be obtained from an authorized instrumented client/test build recording
its existing StartPathImmediately callback, or by extending isolated native
emulation only after the required IL2CPP graph/list/runtime state is verified.
No such complete reference cases were available or fabricated here. Do not replace
the absent official pipeline with a locally guessed callback/rotation routine and
label the result an official path. Nonhorizontal smoothing and all preview-based
movement remain blocked; all three navigation seeds stay until replacement is
validated across the necessary general-map consumers. House interior work remains
out of scope; entry and exit remain supported.

## Obtaining a complete official vectorPath (phase 29 feasibility check)

**A game account is not currently required for further offline research.** The
public official APK, its verified graph caches and the current bounded ARM64
emulator are available. No credentials were requested, read, transmitted or used.
This environment has no `adb`, Android emulator, qemu-aarch64 or Unity executable
on PATH, so a complete Android/Unity client run has not been performed. Absence of
those programs does not prove a game login is required for path calculation.

A further isolated probe ran the actual `Funnel.Calculate` seven-argument numeric
kernel at `0x23597a4`. Metadata parameter names are left, right, numPortals,
startIndex, funnelPath, maxCorners and lastCorner. Native loads/stores establish
Vector2 array length at +0x18/data at +0x20 and the output integer List's backing
array at +0x10/count at +0x18/version at +0x1c. The probe supplied bounded,
preallocated synthetic ABI memory, a marked initialized metadata state and inert
unused method-reference slots. It did **not** initialize a real IL2CPP runtime.
All execution was restricted to the kernel's address range; allocation, metadata
resolution, logging, exceptions or another runtime branch would stop the probe.
Three successful samples exercised 197 unique instruction addresses. Desktop and
Android Python hosts returned the same corner indices and lastCorner=true:

| Left portals | Right portals | Corner indices |
| --- | --- | --- |
| (0,0), (1,1), (3,0) | (0,0), (1,-1), (3,0) | 0, 2 |
| (0,0), (1,2), (2,2), (3,4) | (0,0), (1,1), (2,1), (3,4) | 0, 2, 3 |
| (0,0), (0,1), (1,2), (2,2) | (0,0), (1,0), (2,1), (2,2) | 0, 3 |

This demonstrates that more of the official numeric algorithm can be evaluated
without a server/account. It is not a full vectorPath oracle: the synthetic ABI
setup bypasses normal managed initialization and supplies portal arrays directly.
The probe and output remain private research files outside Git, rather than being
promoted to a production decoder or movement authority.

### Remaining offline work and optional external assistance

The next offline work is to validate input/output layouts for Unwrap and the
three-argument Calculate wrapper, accumulated portal transforms and index-to-3D
reconstruction, then reproduce StartEndModifier and Seeker modifier settings with
verified graph/node state. Each unresolved runtime call must remain a stop, not a
locally guessed algorithm substituted into the reference run. Known graph digest,
ordered corridor and start/end XYZ are available from current verified caches;
complete initialized graph/List/Path state and output parity are not yet proven.
No new access permission is needed for this investigation.

If independent client traces are supplied to accelerate validation, the smallest
useful assistance is a few **sanitized path records**, not an account/password or
just a gameplay screenshot. An authorized client/test build must expose the actual
StartPathImmediately callback, with graph version/digest, start/end world XYZ,
Seeker mask, enabled modifiers/settings, complete/error status, node corridor and
ordered vectorPath before/after modifiers. Include a flat control, a slope and an
overlapping-height case. A stock logged-in client or account alone does not provide
that internal output. A test scene may permit offline collection; whether a
particular client build requires login to load its scene has not been established.
If collection requires live gameplay, the user should run it themselves and share
only the path record, without session tokens or credentials.

No complete official vectorPath was obtained during this feasibility check; no
seed was removed and no movement restriction was relaxed. This phase changes
research documentation only, so application regression suites were not rerun.

## Endpoint preparation and native branch oracle (phase 30)

Further read-only disassembly establishes the following chain in the pinned
ARM64 binary:

- StartEndModifier's constructor (`0x24d30b4`) writes integer mode 3 to both
  endpoint settings (+0x1c and +0x20).
- `Snap` (`0x24d2a10`) selects the first/last node from Path.path, reads its Int3
  position and converts it with the official Int3-to-Vector3 function. Its verified
  switch table at `0x37f3360` sends mode 3 to code returning Path's already
  adjusted start/end coordinates at +0xf8/+0x104. Mode 0 returns node position.
  This conclusion follows the actual numeric switch; no guessed enum decoder was
  used to assign authority.
- `ABPath.Prepare` (`0x234d214`) copies Path.enabledTags (+0xac) into the nearest
  constraint's tag field (+0x20), calls AstarPath.GetNearest (`0x1a7a794`) for the
  start and end, writes back adjusted points, and calls Path.CanTraverse
  (`0x2d95850`). It also invokes constraint/path virtual methods. Thus supplying
  locally projected endpoints to Snap would not validate the missing upstream
  nearest-node/constraint behavior.
- Seeker.RunModifiers iterates the runtime modifier list and dispatches modifier
  interface calls. A complete oracle must retain actual registered ordering and
  settings; manually concatenating guessed transformations is insufficient.

The new optional `tools.review_navigation_endpoints` probe executes only Snap's
reviewed native branches and their actual List element/Int3 conversion helpers.
It uses synthetic preallocated ABI memory, explicit initialized-state slots, a
2,048-instruction ceiling, a strict instruction-address allowlist, and the pinned
library digest/size check from the rotation tool. Unknown runtime calls stop; no
allocator, class initializer or substitute nearest-node implementation is hooked.

```console
python -m tools.review_navigation_endpoints --libil2cpp /path/to/libil2cpp.so
```

Twelve branch cases exercised 105 unique instruction addresses. Fixtures include
start/end at different heights with the same X/Z, signed coordinates and both
endpoint modes 0 and 3. Desktop/Android host output is byte-identical. Mode 3
returns the supplied adjusted start/end values; mode 0 returns the supplied first/
last node positions at the official Int3 scale. **These fixtures do not assert
that supplied endpoints are correct GetNearest results.** The probe outputs
`can_send_packets=false` and explicitly identifies its synthetic ABI scope.
Both hosts pass the 28 focused oracle/navigation guard tests, now including
rejection of an unreviewed library before endpoint emulation imports. No runtime
application behavior changed, and full suites were not rerun for this tool phase.

The complete vectorPath gap is now more specific: instantiate and verify the
actual Recast node/nearest-constraint state, run ABPath.Prepare with real start/end
XYZ and active mask, preserve its returned endpoints/node corridor, then apply
the verified modifier sequence and nonplanar portal transformation. Current
partial math/corner/Snap oracles must not be substituted for that chain. Offline
investigation remains possible without credentials, but complete output parity
has not yet been obtained. Formal movement, nonplanar restrictions, all three
seeds, and house entry/exit behavior remain unchanged.

## Native traversal and nearest constraints (phase 31)

`tools.review_navigation_traversal` now evaluates the pinned official native
Path.CanTraverse (`0x2d95850`), NNConstraint.Suitable (`0x2a8ff80`) and
SuitableGraph (`0x2a8ff50`) with bounded synthetic ABI records. It executes the
actual GraphNode walkability/tag getters where called. Custom traversal providers,
area constraints and graph indices outside 0–31 are explicitly unsupported. No
unknown provider, class initialization or area lookup is replaced with local code.
The same digest/size guard, instruction allowlist and 512-instruction ceiling
apply. This tool is optional research tooling, not a shipped game-data source.

```console
python -m tools.review_navigation_traversal --libil2cpp /path/to/libil2cpp.so
```

The native default policy confirms walkable flag bit 0 and the five tag bits at
19–23, with the active mask selecting allowed tags. Tests include other hierarchy/
graph flag bits to ensure they do not accidentally become tag bits. Native nearest
suitability additionally respects independent constrainWalkability, desired
walkable value and constrainTags switches. SuitableGraph independently checks its
graph mask; node tags and graph selection are not interchangeable.

Both hosts return identical outputs for 960 default flag/tag cases, 64 nearest
constraint-switch cases and 128 graph-mask cases (1,152 total). Four explicit
unsupported-state probes reject area/provider/unknown-kind/out-of-range-index
requests. The seventeen actual current general-model caches contain 9,075 nodes.
Across all three preview masks, 51 model/mode comparisons confirm that the existing
PreviewMesh walkable set matches the official default CanTraverse and Suitable
results on every serialized flag value. This validates default local filtering,
not the player's live active mask or a custom traversal provider.

### Why the complete graph state still matters

GraphNode.get_Area (`0x2d93f00`) reads bits 1–17 as a **hierarchical node index**,
then calls `HierarchicalGraph.GetConnectedComponent` (`0x2d84a14`) through the
active AstarPath hierarchy. Those bits are not a self-contained serialized area
ID. NNConstraint.Suitable invokes this lookup when constrainArea is enabled and
area is nonnegative. PathNNConstraint.SetStart (`0x2a90220`) obtains the starting
node's runtime area. A guessed area from raw flags would therefore produce an
invalid nearest-node oracle, even if the geometric triangles look correct.

Metadata identifies the hierarchy's children, connections, areas, dirty-node and
free-index structures. Relevant native entry points are RecalculateAll
`0x2d854c8`, FindHierarchicalNodeChildren `0x2d84edc`, FloodFill `0x2d85198`, and
RecalculateIfNecessary `0x2d853bc`. Nearest search also uses the Recast BBTree
(node lookup/tree/leaf structures), with QueryClosest `0x2843a34` and
SearchBoxClosest `0x28440d4` (and separate XZ forms). The concrete next offline
step is to verify reconstruction of those structures from one complete reviewed
graph, then compare area-filtered nearest results before ABPath/Seeker integration.
The current serialized triangle/connection reader alone is not that complete
runtime state.

Offline investigation can still advance; there is no new authentication or
external access blocker and no need for credentials. The missing evidence is
verified hierarchy/BBTree initialization and full native output parity, not just
another sample coordinate. Both hosts pass 28 focused tests including unknown
library rejection for the new oracle. Application runtime is unchanged; no new
formal movement authority, seed removal, live server claim or full-suite rerun was
introduced in this research-tool phase.

## Native hierarchy flood-fill and BBTree construction audit (phase 32)

The optional `tools.review_navigation_areas` now executes the official
HierarchicalGraph.FloodFill (`0x2d85198`) and GetConnectedComponent (`0x2d84a14`)
with preallocated synthetic hierarchy adjacency. Actual native integer Stack
Push/Pop, List element access and integer Max helpers also execute; no local
flood-fill implementation is substituted into the native run. A separate Python
connected-component calculation checks the returned table afterward.

```console
python -m tools.review_navigation_areas --libil2cpp /path/to/libil2cpp.so
```

Inputs are bounded to 256 hierarchy nodes plus reserved index zero, require valid
reciprocal links, and reject duplicates, self-links, bad indices and malformed
arrays before emulation. Reciprocal input is this probe's scope, not a claim that
all serialized triangle arcs are reciprocal. Native instruction addresses are
allowlisted, allocation/unknown runtime paths stop, and each call has a fixed
instruction ceiling. A pinned digest and synthetic initialized ABI records remain
required. This is not complete Unity managed-runtime initialization.

Nineteen cases (empty/reserved-only, isolated nodes, cycles and seeded graphs of
4–64 nodes at multiple densities) produce identical outputs on desktop and
Android hosts. All match the independent component partition. Reserved index zero
remains zero; the native component-count property includes the reserved component
and is at least one. The hierarchy version increments after filling. Each area
entry is read through the official GetConnectedComponent function, not only by
looking at raw memory. The 29 focused tests pass on both hosts, including new
malformed hierarchy checks. No application runtime code changed.

This validates the **given-hierarchy adjacency → Area table** stage only. It does
not establish that one triangle should equal one hierarchy node, or that raw
serialized hierarchical indices remain valid after loading. Those assumptions
were not made. Official FindHierarchicalNodeChildren/RecalculateAll still need
verified triangle-node/object/callback state to produce the actual grouped
hierarchy.

BBTree disassembly additionally confirms RebuildFromInternal (`0x2842f6c`)
starts with NodeBounds (`0x28433a4`), obtains a box through GetBox (`0x2842ea4`),
uses leaves of at most four entries, and otherwise partitions through SplitByX
(`0x284327c`) / SplitByZ (`0x2843310`) and recurses. NodeBounds combines indexed
IntRect inputs using actual integer min/max helpers. Tree boxes have a 28-byte
stride in this binary; leaf node lookup slots are managed references. Capacity
methods, reference write barriers and node/vertex ownership must be validated
before treating a locally prepared tree as official initialized state. No BBTree
output or complete GetNearest success is claimed from disassembly alone.

The remaining concrete evidence gap is now two initializers: official triangle
nodes → grouped hierarchy, and official node bounds/references → initialized
BBTree. Afterwards, area-constrained GetNearest and ABPath endpoint preparation
can be compared without inventing either table. Offline investigation remains
possible; there was no access/authentication blocker, and no account is needed
for the next isolated probes. The three seeds and all unverified movement guards
remain. Full application suites were not repeated for this research-only change;
the latest recorded application full-suite results remain phase 26.

## Native BBTree internal construction (phase 33)

`tools.review_navigation_bbtree` executes the pinned official
RebuildFromInternal (`0x2842f6c`), NodeBounds, split helpers, GetBox and capacity
checks, with synthetic initialized ABI records and preallocated buffers. It also
executes the native identical-class type-check branch and reference write barrier
with GC marking disabled in the synthetic state. No Python tree builder is
substituted. Allocation, unreviewed branches and instruction-limit exhaustion
fail closed. This is not complete managed-runtime or live graph initialization.

```console
python -m tools.review_navigation_bbtree --libil2cpp /path/to/libil2cpp.so
```

Nine cases cover 1, 4, 5, 8, 17, 64, 256 and 512 distinct input rectangles, plus
65 coincident rectangles/centers to exercise the degenerate split fallback.
Desktop and Android Python hosts return identical native boxes and references.
Validation checks exact input-reference preservation (including pointer alignment),
leaf padding/capacity, reachable acyclic box links and exact recursive bounds.
Input limits are 512 nodes and bounded integer coordinates; binary digest and
size checks run before loading optional emulator dependencies. Both hosts pass
31 focused tests, including malformed input, duplicate references, cycles,
unreachable boxes and incorrect bounds. These are host tests, not Android device
acceptance. Full application suites were not repeated for tools-only changes;
phase 26 remains the latest recorded complete application regression.

This proves the internal builder for supplied rectangles and centers, not their
extraction from official triangle objects. Triangle vertex ownership, native
center rounding and complete RebuildFrom initialization still require comparison
before connecting a real map to GetNearest.

Further disassembly of FindHierarchicalNodeChildren and its callback
(`0x2d85d64`) confirms that the callback reads hierarchical index from flags bits
1–17. An already assigned different group is added to the group adjacency list
unless already present. An unassigned node is accepted only when walkable and
the current children count is at most 255 (then appended). This is evidence for
a bounded grouped traversal, not proof of a locally invented grouping algorithm.
The callback, queue operations, virtual GetConnections dispatch and full grouping
initialization have not yet been run together against official output.

Consequently area-constrained GetNearest and complete vectorPath remain
unverified. Next work is the native grouped traversal and triangle-bound/center
initializers, followed by combined nearest-point queries. No account or new
permission is required for those offline probes; the obstacle is unverified ABI
state and output equivalence. All movement guards and the three remaining seeds
are retained. No application runtime behavior changed in this phase.

## Native group callbacks, queue and triangle access (phase 34)

`tools.review_navigation_groups` now executes FindHierarchicalNodeChildren
(`0x2d84edc`) together with actual MeshNode.GetConnections (`0x2d94558`), the
hierarchy callback (`0x2d85d64`), Queue.Enqueue/Dequeue/MoveNext and empty-queue
Clear. The synthetic node vtable points to the official GetConnections method;
the synthetic delegate invokes the official callback. These dispatch records are
prepared test state, not recovered full Unity runtime state. Native reference
write barriers run with inactive GC marking. Buffers are preallocated, binary
hashes are pinned, native instruction addresses are allowlisted, and allocation
or other unreviewed branches stop the probe.

Fifteen cases cover chains of 1–256 nodes, blocked intermediate nodes, a star,
cycle/disconnected node and seeded directed graphs with mixed walkability.
Desktop and Android hosts produce identical child order, updated flags and empty
final queue. All match an independent traversal over the supplied directed arcs.
The probe validates pointer alignment, child count and duplicate references. It
requires a walkable start and bounds the complete input to 256 nodes. This tests
one group, not RecalculateAll or multiple groups with cross-group links. The
existing FloodFill probe still tests supplied hierarchy adjacency separately;
these are not yet a complete real-map hierarchy/Area initialization.

`tools.review_navigation_vertices` executes TriangleMeshNode.GetVertices
(`0x2832670`), graph-index/holder lookup, native interface dispatch to
NavmeshBase.GetVertex (`0x27a12ec`), and tile vertex access (`0x24c6354`) on a
synthetic initialized single-tile holder. It then runs the official IntRect
constructor/expansion and integer min/max helpers. Nine cases cover vertex
permutations, repeated indices, negative coordinates, mixed heights and the
probe's coordinate bounds. Repeated indices test access/bounds only and are not
accepted as evidence of valid navigation triangles. Both hosts return identical
vertices/bounds, matching the supplied vertices and independently calculated XZ
bounds. This probe does not run the entire BBTree.RebuildFrom caller.

```console
python -m tools.review_navigation_groups --libil2cpp /path/to/libil2cpp.so
python -m tools.review_navigation_vertices --libil2cpp /path/to/libil2cpp.so
```

Center initialization remains incomplete. UpdatePositionFromVertices
(`0x28325e8`) reads three vertices, adds Int3 values and uses the native float32
one-third constant with Int3 multiplication (`0x2d86434`). That method calls
external `modf` via `0xb125f0` before rounding. ELF inspection confirms `modf` is
undefined/imported in both available official libil2cpp and libunity binaries;
neither contains its implementation. No approximate center or substituted host
rounding was represented as full official native output. Completing this path
requires a verified compatible AArch64 runtime implementation/ABI or a separately
validated, explicitly identified external-function model. Such a model would
remain a modeled dependency rather than an entirely official-binary oracle.

The remaining work is multi-group initialization/cross-group deduplication,
verified center initialization and then combined area-constrained GetNearest.
Offline investigation can still advance; there is no account/permission blocker.
The 33 focused tests pass on each host, including malformed graph and vertex
inputs and unknown-binary rejection before optional imports. These are host
regressions, not device/live-server acceptance. No app runtime behavior changed;
full suites were not rerun (latest full results remain phase 26). All movement
guards and the three seeds remain, and these tools cannot authorize movement.

## Composed initialization and explicit modf model (phase 35)

`tools.review_navigation_initialization` composes two bounded offline probe
chains: native triangle vertex access → center calculation with an explicit
external-function model → native BBTree; and native group traversal → group
links → native FloodFill/Area lookup. These remain separate synthetic graph
states, not one complete live graph or a GetNearest/vectorPath oracle.

```console
python -m tools.review_navigation_initialization --libil2cpp /path/to/libil2cpp.so
```

ELF relocation inspection ties the PLT entry `0xb125f0` to the undefined `modf`
symbol at GOT slot `0x4923260`. The optional center mode uses an explicitly
identified mathematical contract model at that import: finite binary64 input in
±100,000,000, integral part truncated toward zero, signed fractional and integral
zero preserved. Integer-ratio decomposition avoids guessed rounding. Tests
compare bit patterns against host libm for 1,010 values including signed zeros,
half values and seeded float32 inputs; NaN/infinity/out-of-domain values reject.
This verifies a bounded contract model, **not the missing Android libm binary**.
The adapter accepts only the three inspected native call return addresses and a
bounded stack output pointer. Unknown callers stop. Default vertex probing does
not enable the model; `--modeled-center` opts into it explicitly, while the
combined command identifies the model in its output and module description.

The actual pinned float constant at `0x37f3af0` is bytes `9faaaa3e`, or
**0.33333298563957214**, not exact 1/3 or float32(1/3). Native
UpdatePositionFromVertices and Int3 addition/multiplication execute unchanged;
only external modf is modeled. Ninety-nine triangle cases (permutations,
repeated indices, extremes, mixed heights and seeded inputs) match a separately
computed float32 sum/scale/ties-to-even reference using that exact constant.
Both hosts return identical results. These centers and native bounds then feed
the official BBTree builder, whose full reference/bounds validation passes.
Repeated-index cases are numerical/ABI probes, not valid navigation triangles.

This exposes a prior overly restrictive **probe** check: with large equal vertex
coordinates, the approximate multiplier can produce a center just outside the
vertex bounding rectangle. BBTree partitioning uses centers but its NodeBounds
uses rectangles. The probe now requires ordered bounded rectangles and bounded
centers independently; it no longer assumes center containment. A regression
covers this evidence-backed case. Application movement/geometry checks were not
changed.

The extended group probe accepts up to 512 supplied nodes and calls the native
group initializer in an explicit deterministic test-root order. Five cases cover
257/300/512-node chains, 32 disconnected nodes and a blocked 512-node chain.
Native child groups, flags and reciprocal group links match an independent
bounded traversal; the links are passed into the existing native Area probe.
Both hosts produce identical combined outputs. This root order is test setup,
not proof of RecalculateAll's root enumeration.

A 300-node cycle deliberately reaches repeated cross-group-link deduplication.
The nonempty List.Contains path requires unresolved generic IndexOf context;
the probe explicitly stops at an unreviewed dispatch sentinel instead of
substituting a local search. This expected rejection is verified in the combined
run. Multiple-group results therefore apply only to the exercised link cases,
not arbitrary maps. Resolving that generic context and real root initialization,
then constructing one shared graph/BBTree/Area state, are still needed before
area-constrained GetNearest can be compared end to end. No GetNearest success
or official Android runtime equivalence is claimed.

Both hosts pass 35 focused tests. No application runtime code changed; complete
application suites were not rerun (latest full results remain phase 26). There
is no account/permission blocker to further offline investigation. All three
seeds, movement guards, and no-packet authority of these probes remain intact.

## Registered generic deduplication and shared hierarchy state (phase 36)

The unresolved nonempty-Contains dispatch from phase 35 is now resolved.
`tools.review_navigation_registration` checks both pinned binary and metadata
hashes, metadata version/type counts, and six concrete Int32 MethodSpec records
against generic method pointers and declaring method names. The checked native
chain is List.Contains (`0x1f50ee0`) → List.IndexOf (`0x1f51960`) → Array.IndexOf
(`0x2a270e0`) → Array.IndexOfImpl (`0x25371d0`) → EqualityComparer.get_Default
(`0x164c9d8`) → GenericEqualityComparer.IndexOf (`0x2ce74f8`), whose integer
comparison executes at `0x20cda5c`. The native memory fence also executes.

The static layout investigation consulted the project's own
[Il2CppDumper registration declarations](https://raw.githubusercontent.com/Perfare/Il2CppDumper/master/Il2CppDumper/Il2Cpp/Il2CppClass.cs).
Layouts were checked against this binary's counts, relocations and method
identities, rather than assuming all version annotations apply unchanged.
The audit records six matching method identities and Int32 type arguments; it
is not a general metadata decoder or managed-runtime constructor.

```console
python -m tools.review_navigation_registration --libil2cpp /path/to/libil2cpp.so --metadata /path/to/global-metadata.dat
python -m tools.review_navigation_initialization --libil2cpp /path/to/libil2cpp.so
```

The grouping probe supplies preinitialized generic contexts and a
GenericEqualityComparer<Int32> instance, then executes the actual native search
chain. No Python equality/search callback substitutes for deduplication. Runtime
comparer construction remains outside this synthetic test scope. Nine grouped
cases now include 257/300/512-node cycles and a 300-node graph with additional
cross-boundary edges, alongside the previous chains/disconnected/blocked cases.
The cycle formerly rejected by the probe now succeeds and deduplicates group
links. All groups, links and flags match independent traversal.

Group initialization, cross-group links and FloodFill now run in **one emulator
memory state**. GraphNode.get_Area (`0x2d93f00`) reads each node's assigned
hierarchical index through a synthetic initialized AstarPath.active reference
into that same hierarchy. NNConstraint.Suitable then runs against those nodes
with area 0, area 1 and unrestricted area -1, retaining walkability checks.
Native per-node areas and suitability match independent expectations. The Area
output is additionally compared with the separate native Area oracle. The root
iteration is still explicit test order; RecalculateAll and a complete live
AstarPath instance are not claimed.

For modf, the finite-domain behavior was checked against the published
[AOSP Bionic implementation](https://raw.githubusercontent.com/aosp-mirror/platform_bionic/master/libm/upstream-freebsd/lib/msun/src/s_modf.c).
That implementation removes fractional mantissa bits, preserves signed zero and
subtracts the integral part. An independent binary64 mask reference now tests
exponent boundaries, neighboring values and subnormals against the ratio-based
model. This supports finite-domain mathematical equivalence; it does not pin the
specific Android OS/libm binary used by a game client. The optional model remains
explicitly identified, and NaN/infinity/out-of-domain inputs still reject.

Both hosts produce identical six-method registration audits and complete probe
outputs (99 modeled-center/BBTree cases and nine shared-hierarchy cases), and
pass 36 focused tests. No application runtime behavior changed; latest full
application regression results remain phase 26, without new device/live-server
acceptance or remote CI claims.

End-to-end GetNearest is still **not verified**. NavmeshBase.GetNearest
(`0x27a375c`) dispatches into GetNearestForce (`0x27a3844`), which calls
GetTileCoordinates (`0x27a1618`) before searching tile trees. The graph transform,
tile dimensions/ownership, nearest-point geometry and outer AstarPath constraint
selection still need a single verified graph state and combined execution. The
now-shared hierarchy state is a prerequisite, not that result. Offline work can
continue without credentials; all three seeds and movement guards remain.

## Native graph-level nearest-point integration (phase 37)

`tools.review_navigation_nearest` now executes an end-to-end **graph-level**
native query on bounded synthetic initialized state: NavmeshBase.GetNearest
(`0x27a375c`) / GetNearestForce (`0x27a3844`) → GetTileCoordinates
(`0x27a1618`) → GraphTransform.InverseTransform (`0x22d23f0`) → tile BBTree
QueryClosest/SearchBoxClosest → TriangleMeshNode.ClosestPointOnNode
(`0x2832dd8`) → native closest-point geometry (`0x2a98e20`). Native vertex
reads, float32 math, distance comparisons, reference barriers and (for force
queries) walkability constraints execute. Python does not supply the nearest
node or point during emulation.

```console
python -m tools.review_navigation_nearest --libil2cpp /path/to/libil2cpp.so
```

The probe reuses pinned vertex/center preparation and the official BBTree
builder. It materializes the returned leaf box and references in a synthetic
single-tile RecastGraph/NavmeshBase state with initialized vtables and metadata
slots. This is an explicit test fixture, not proof of complete runtime loading.
Center preparation retains the separately identified modf model. At most four
triangles are accepted; internal-tree traversal, multiple tiles and XZ-only
nearest queries remain outside the execution allowlist.

Translation-only inverse transform and the inverse-matrix branch both execute.
The matrix cases contain an initialized inverse translation matrix, not an
unverified general rotation or scale. Actual RecastGraph tile-size getters run,
with the test fixture using 10-unit tiles. Native coordinate conversion truncates
toward zero before graph search clamps tile selection; negative-coordinate cases
explicitly check this rather than assuming mathematical floor.

384 cases cover flat/sloping geometry, two/four vertically overlapping
triangles, inside/edge/corner/outside queries, negative coordinates, translated
origins, both transform branches, all-excluded and selectively walkable nodes.
An independent double-precision plane projection plus clamped edge comparison
checks nearest node and point (absolute coordinate tolerance 0.0002). Expected
tile coordinates are checked separately. Both desktop and Android Python hosts
produce identical native outputs. Both hosts pass 38 focused tests, including
unknown-library rejection, degenerate geometry, input bounds and independent
reference cases. The vertex oracle exposes private composition state only to
these offline tools; no application behavior or source-data authority changed.

This is the first bounded graph-level GetNearest integration result. It is
**not** outer AstarPath.GetNearest, ABPath preparation, complete vectorPath,
real-map coverage, or Android-device/live-server acceptance. The prior hierarchy
probe validates area state separately; this graph query currently applies only
walkability constraints, without merging hierarchy/Area into this graph state.
Next work is internal BBTree branches, multiple-tile transforms/ownership,
combined Area/tag constraints and outer AstarPath selection on verified graph
fixtures, followed by actual official map inputs. No movement capability is
unlocked by these tests. All three seeds and existing guards remain; complete
application suites were not rerun (latest full results remain phase 26).

## Outer GetNearest, multiple tiles and official whole-mesh inputs (phase 38)

The nearest probe now executes outer AstarPath.GetNearest (`0x1a7a794` /
`0x1a7a7c4`), its graph-array access, SuitableGraph, graph search/fallback,
final suitability/distance checks and NNInfo construction. Both full-search and
normal-search modes run; the latter can reject the first graph result and invoke
GetNearestForce with constraints. Graph masks and distance limits execute in the
native code. The test AstarPath/Data graph array contains one graph, so selecting
among multiple different graphs and prioritized-graph behavior remain untested.

The probe now supports bounded 2×2 tiles, up to 512 triangles, and native BBTree
internal traversal (including child-distance ordering). Each tile receives its
own native-built boxes and node lookup references; native node vertex indices
encode tile ownership. The graph settings supply cell size and tile cell counts,
and source world vertices remain intact. Query execution has a bounded 200,000
instruction ceiling; this is an offline research limit, not a changed application
download or movement limit. Larger meshes reject rather than truncate.

```console
python -m tools.review_navigation_outer --libil2cpp /path/to/libil2cpp.so
python -m tools.review_navigation_outer --libil2cpp /path/to/libil2cpp.so --cache-dir /path/to/reviewed/navigation-caches
```

144 synthetic cases check one/four tiles, tile boundaries, negative coordinates,
full/normal search, graph exclusion and distance limits. The prior 384 graph-level
cases were rerun on desktop after the memory-layout changes. All compare against
independent geometry. Boundary ties may select another eligible triangle only
when its independently computed closest point still matches (coordinate tolerance
0.0002) and its squared distance remains minimal within 0.001; arbitrary node
mismatches are not accepted.

The official-data command reads complete cached official A* files, first enforcing
the model-specific SHA-256 and 8 MiB cap, then the existing strict format review.
It uses the complete vertices/triangles, actual node flags, origin, cell size and
tile sizes. It does not download files, mutate the database, or substitute seed
geometry. Thirteen complete reviewed maps (3,042 triangles) are within the probe
bound; three query positions per map, two search modes and land/sky tag masks
produce 156 native outer-query cases. Both hosts produce identical outputs, and
all cases match independent geometry. This is official input data executed in a
prepared emulator runtime, not execution by the installed official client.

Four reviewed maps are explicitly excluded from this probe run, without dropping
triangles: M12050 (844 nodes), M11139 (605), M12600 (513), and M58001 (4,071).
Player houses are excluded by scope. All reviewed official cache formats are
single-tile, so current multiple-tile coverage is synthetic only. Area constraints
were verified in the prior hierarchy probe but are not yet merged into these
outer-query fixtures. Sea tag masks, graph prioritization and multi-graph selection
are not claimed by this run.

Both hosts pass 39 focused tests, and shared-core parity remains 185 sources.
No application runtime code changed; full application-suite results remain the
previous phase-26 record. These are desktop/Android Python-host tests, not APK,
device, official-server or remote CI acceptance. The explicit modf model remains.

Full-path investigation identifies the next required native state:
ABPath.Prepare (`0x234d214`), Initialize (`0x234d6f4`) and CalculateStep
(`0x234da68`) use PathHandler.GetPathNode (`0x2e9a940`), PathNode costs and
parents, BinaryHeap.Add (`0x2d7f92c`)/Remove (`0x2d7fba0`), and virtual node
expansion before tracing. Those structures and transitions have not been executed
together, and no complete vectorPath or postprocessed path is claimed. The next
step is a bounded native PathHandler/heap fixture, combining the verified nearest
and hierarchy stages before tracing and modifiers. All three seeds and all
unverified-movement guards remain, with no changes pushed.


## Phase 39 — native path state, queue and supplied-parent tracing

`tools/review_navigation_path_state.py` pins the same official library digest
before optional emulator imports. It executes PathHandler.GetPathNode,
BinaryHeap.Add/DecreaseKey/Remove and Path.Trace in prepared, bounded memory.
Fourteen reproducible synthetic cases cover 1–256 nodes, decrease-key, equal
priorities, branching parent chains and positive/negative heights. All parent
chains and G/H costs are supplied inputs; ABPath does not generate these paths.
The two Python hosts produce identical results. These are emulated ARM64 official
instructions, not Android device runs or execution in the official game client.

Each removal is checked for a valid unique node reference, cleared heap index,
and nondecreasing primary F cost. Trace is checked against an independent parent
walk, node order and exact float32 Int3-to-vector conversion. Cyclic parents,
invalid indices, noninteger/negative costs, oversized fixtures and invalid
positions are rejected before fixture memory is written. The probe preallocates
lists and models inactive GC; it neither downloads data nor changes the app.

An important native tie case is now preserved: for G/H pairs `(0,100)`,
`(1,99)`, `(2,98)`, insertion followed by removal yields node order `[2,0,1]`.
DecreaseKey insertion favors higher G at equal F, while Remove's child selection
favors lower G. A conventional global `(F,G)` or `(F,-G)` sort is therefore not
an equivalent queue oracle. The tool records complete native ordering, verifies
primary priority, and separately asserts this minimal tie fixture.

Further inspection identifies TriangleMeshNode.Open (`0x2833724`) reverse
connection traversal, Path.CanTraverse (`0x2d95938`), node penalty plus tag
penalty in GetTraversalCost (`0x2d95a34`), and UpdateRecursiveG (`0x2833638`).
Open uses endpoint-flag-dependent virtual GetConnectionSpecialCost and updates
previously reached nodes recursively when a cheaper parent is found. These
transitions have not yet been executed together with ABPath.Initialize and
CalculateStep. The next required work is to materialize their path IDs, virtual
dispatch, tag penalties, heuristic configuration and endpoint state, then compare
search-generated parents before invoking Trace and the player's modifiers.

Both hosts pass 41 focused tests. The high/low positions here verify conversion
and trace ordering only, not nonplanar route validity. Land/sea/sky traversal
filters remain independently tested by earlier probes; they are not part of a
complete mode-specific path comparison. No full vectorPath, postprocessing,
application-wide rerun, remote CI or device acceptance is claimed. All three
navigation seeds and movement guards remain, and no changes are pushed.

## Phase 40 — prepared native search and endpoint modifier

`tools/review_navigation_search.py` now executes a connected native chain:
ABPath.Initialize and CalculateStep, TriangleMeshNode.Open, CanTraverse,
GetTraversalCost, CalculateHScore, GetConnectionSpecialCost, UpdateRecursiveG,
BinaryHeap, Path.Trace, and StartEndModifier.Apply/Snap (both endpoint modes 3).
The parent chain is generated by native search, unlike phase 39. The supplied
state is a bounded graph, endpoint node/point selection, path ID, tag penalties,
zero-scaled Manhattan heuristic and target flag; this is **not ABPath.Prepare**.
A separate deliberately inconsistent heuristic fixture verifies reopening and
three recursive G-update calls, including descendant propagation.

Thirty-nine synthetic cases run identically on desktop and Android Python hosts:
land/sea/sky masks, flat and positive/negative height corridors, shifted endpoint
positions, tag/node penalties, blocked corridors, same-node endpoints and recursive
cost updates. Eighteen blocked cases reach the native no-route error boundary;
the probe stops there rather than emulating error-string construction. Successful
cases reach native completion and Trace, then execute the endpoint modifier.
An independent Bellman-Ford calculation checks reachability and minimum total
cost using rounded 3-D distances and the endpoint scaling rule. It also checks
that every route edge is permitted and that the traced vectors match its nodes.
Endpoint-modified vectors are checked separately, including the two-point output
for a one-node path. Equal-cost route identity is not replaced with a Python heap.

Optional `--cache-dir` reads only existing, hash-pinned reviewed cache ZIPs. Two
complete ordinary graphs fit the 128-node bound: M13224 (85 nodes) and M13216
(81 nodes). Their vertices use the verified native center calculation; their
connections, costs, flags and penalties come from the official caches. Twelve
searches (three endpoint pairs per graph, land and sky) pass the independent checks
and produce identical host outputs. Both graphs have zero sea-traversable nodes,
which is reported explicitly; sea coverage here is synthetic. Fifteen other
ordinary graphs exceed this probe's bound and are excluded without truncation.
This does not change the product download limit or fetch any additional data.

The harness rejects self/duplicate/out-of-range graph references,
coincident connected centers, invalid flags/points/penalties and potential
28-bit edge-cost or uint32 G/F overflow before writing fixture state. Graph cycles
are allowed; resulting path cycles are rejected. There are at most 128 nodes,
32 edges per node and two million instructions per native entry. Unreviewed calls,
including the longer-search clock branch, stop execution. All results retain
`can_send_packets=false`.

The official-library SHA remains pinned. Two non-path dependencies are explicitly
modeled: the previously verified finite-domain `modf` contract (now also called
from Int3 magnitude rounding), and a single-thread monitor enter/exit at exact
caller/object/stack-pointer boundaries. Managed lists and method dispatch are
preallocated synthetic state with inactive GC. The monitor model is not evidence
of concurrent IL2CPP runtime equivalence. These runs are offline ARM64 instruction
emulation, not official-client, APK, device, live-server or remote-CI acceptance.

The final player path is still unverified. Prepare/GetNearest and Area constraints
are not joined to this search fixture; actual heuristic/runtime initialization and
modifier registration are not reproduced. Funnel's nonplanar Unwrap, portal repair,
corner-to-3D reconstruction and Seeker's actual modifier order still need connected
validation before applying MoveController's first-point removal. Inspection of
Funnel.Unwrap (`0x235887c`), the three-argument Calculate wrapper (`0x2358f78`)
and FunnelModifier.Apply (`0x24cd3a8`) confirms further managed list/pool and portal
state dependencies. The isolated corner/rotation probes are not substituted for
that chain. These are concrete offline implementation gaps, not an authentication
or permission block, and no game credentials are needed for the next investigation.

Both hosts pass 43 focused tests. The 14 phase-39 path-state cases and 99 native
vertex/center cases are rerun on both hosts. Application runtime behavior remains
unchanged; full application-suite results remain phase 26. All three navigation
seeds and movement guards remain; house entry/exit scope is unchanged. No changes
are pushed.

## Phase 41 — joined preparation and nonplanar funnel kernel

`tools/review_navigation_prepare.py` joins native ABPath.Prepare, outer
AstarPath.GetNearest, PathNNConstraint.SetStart, GraphNode.Area, Initialize,
CalculateStep, Trace and StartEndModifier in **one VM graph state**. Unlike phase
40, the original XYZ endpoints are inputs; native Prepare chooses nodes, clamps
points, converts them to Int3 and marks the target. Its selected nodes/points are
checked against independent triangle geometry, tag eligibility and start Area;
the resulting search is checked against the independent cost reference.

The graph uses complete triangle geometry and native BBTree output. Hierarchy
flags/Area values are computed by the existing native grouping/FloodFill probe
in a separate VM, then installed into this graph. Stale serialized hierarchy bits
are cleared before assigning the recomputed groups. This is prepared runtime
state, not a run of the official deserializer/RecalculateAll. The multiple-group
probe now also supports all-unwalkable graphs: native FloodFill leaves reserved
Area zero, and Prepare fails rather than inventing a traversable node.

Twenty-five synthetic cases cover land/sea/sky/empty masks, positive and negative
slopes, disconnected components and an all-unwalkable mesh. Area filtering may
snap the requested endpoint to the nearest eligible node in the start component;
that behavior is checked rather than silently treating the requested coordinates
as the reached endpoint. Full nearest search, zero-scaled Manhattan heuristic,
zero embedding pivots and prepared single-thread TLS/canary are explicit fixture
settings. They are not claimed as every live player's settings.

Two full reviewed official graphs, M13224 (85 nodes) and M13216 (81 nodes), run
18 original-XYZ query cases through Prepare. Twelve land/sky cases complete and
pass the independent checks; six sea cases reach the native error boundary during
Prepare because neither map contains eligible sea nodes. Error-string construction
is not emulated. Fifteen other ordinary graphs exceed the 128-node probe limit and
are excluded without truncation. No new downloads or product limits changed.

### Nonplanar funnel and explicit runtime dependencies

`tools/review_navigation_unwrap.py` executes native Funnel.Unwrap/UnwrapHelper,
collinearity tests and quaternion multiplication. The actual IL2CPP
Quaternion.FromToRotation wrapper calls a guarded ABI bridge which executes the
pinned **libunity.so** function in a second ARM64 VM. It does not substitute a
Python rotation formula. Vector3's native static constructor is executed, including
verification that its forward vector at static offset 0x48 is `(0,0,1)`; it is not
guessed from metadata field ordering. Inputs remain supplied portal corridors.

`tools/review_navigation_funnel_wrapper.py` executes the three-argument native
Funnel.Calculate wrapper, Unwrap, FixFunnel, the corner-search kernel and 3-D
reconstruction, with split-at-every-portal both false and true. Only its pool
claim/release boundaries are replaced by bounded preallocated arrays/lists. Every
bridge validates exact native call sites, capacity, pointer ownership and release
lifecycle. No path-math or portal-selection function is replaced. These models do
not prove the full managed pool/GC implementation or concurrent runtime behavior.

Seventy-two cases (36 geometric corridors with both split settings) cover flat,
folded, rotated, translated and differently scaled geometry. Independent checks
verify local edge-length preservation during unfolding, endpoint preservation,
corner-index reconstruction, and that each split point lies on its corresponding
original 3-D portal. The native split setting materially changes folded outputs;
its default must not be assumed to match an existing player's component settings.
All 25 preparation, 18 official-input and 72 funnel cases have byte-identical
outputs on desktop and Android Python hosts. No installed-client/device run is
implied.

### Remaining final-player-path gap

The preparation/search and funnel tools are not yet one end-to-end player oracle.
Funnel currently receives supplied portal lists: native ConstructFunnelPortals,
TriangleMeshNode.GetPortal, part splitting and FunnelModifier.Apply must still be
joined to the actual searched corridor. Seeker's registration/sort/dispatch and
MoveController's final first-point removal also need a connected execution check.
Read-only inspection identifies StartEndModifier.Order=0 and FunnelModifier.Order=10;
this alone does not establish the whole registered list or its runtime settings.

The verified decoded MoveController initialization explicitly adds **or reuses**
Seeker and FunnelModifier and sets the Land mask. Thus constructor defaults cannot
establish settings for an existing serialized component. The next evidence is the
player object's actual prefab/component settings and/or the complete initialization
and registration chain, alongside native portal extraction. No credential or
permission block has occurred. Do not request account passwords or enable movement
to obtain a reference result.

Both hosts pass 47 focused tests. Native regression runs also cover the 384 nearest,
9 multiple-group, 39 search, 99 vertex/center and 14 path-state cases. These remain
research tools; app runtime behavior is unchanged, full app-suite results remain
phase 26, and no remote CI or live-server acceptance is claimed. Three navigation
seeds and all movement guards remain; house entry/exit scope is unchanged. Changes
remain local and are not pushed.


## Phase 42: searched corridors through native portals and funnel

The local research pipeline now composes native Prepare/GetNearest, search/Trace,
TriangleMeshNode.GetPortal and the nonplanar Funnel.Calculate wrapper. It consumes
the actual searched node sequence and serialized connection edge indices; portal
coordinates are no longer manually supplied. Invalid, missing, cross-tile or
unsupported edge records are rejected. The probe remains bounded to 128 nodes,
uses prepared single-tile state, and never permits packet transmission.

Twelve synthetic queries cover rising/falling folded terrain and land/sea/sky/empty
masks. Eighteen queries on the complete M13224 and M13216 official graphs yield
12 successful searches (24 funnel profiles, split false/true) and six expected sea
Prepare error boundaries. Fifteen larger reviewed ordinary graphs remain excluded
without truncation. All synthetic, official-input and four native modifier-order
comparison results are byte-identical across the desktop and Android Python hosts.

The native Seeker registration comparison delegate, interface Order getters and
Int32 comparison establish StartEnd order 0 before Funnel order 10 for these two
components. This is not execution of complete registration, List.Sort or dispatch.

Further verified Lua evidence refines phase 41's initialization uncertainty:
RoleController.New creates a fresh GameObject, then constructs MoveController,
and only afterwards ModelController. The verified decoded RoleController SHA-256
is af01c2a8e1b785ff9bc53f080b9282ebcd3b31c275ec8f3ff10e1a0f869ce8e9.
This fresh-root initialization path supports examining new-component defaults;
it does not establish absence of subsequent changes or the full modifier inventory.
The 36 decoded Lua files inspected contain no explicit funnel-setting mutation,
which is not a claim about the entire official Lua corpus.

Remaining gaps are native part splitting/ConstructFunnelPortals/FunnelModifier.Apply,
complete Seeker registration and dispatch, and the player's final point processing.
The composed probe supplies single-part boundaries and runs separate prepared VMs;
its candidate outputs are not yet an official final-player-path oracle. Coverage
also remains limited to two full ordinary graphs and explicit fixture settings.
No credentials or permissions block this research. No app runtime behavior changes,
seed deletion, device/live-server acceptance, full app-suite rerun or remote CI run
is claimed. Both hosts pass 49 focused tests. The final three navigation seeds and
movement guards remain, with house entry/exit retained. Changes remain local.


## Phase 43: native parts, dispatch tracing and player callback source

`review_navigation_parts.py` now executes native Funnel.SplitIntoParts and
ConstructFunnelPortals, including virtual TriangleMeshNode.GetPortal calls. It
consumes the searched corridor and native StartEnd-modified vector list. For the
supported same-tile triangle corridor it verifies the native part's indices,
endpoint values, non-link flag and all constructed left/right portal points.
Only bounded pool allocations are modeled; graph state, type/interface tables and
list storage remain explicitly prepared. Cross-tile/off-mesh links are rejected.
This does not verify general mixed-graph or off-mesh splitting.

The composed pipeline uses these native part results instead of supplying a
single-part boundary. Its 12 synthetic and 18 official-map queries have identical
outputs on both Python hosts; all native funnel vectors also remain identical to
phase 42. Twelve official land/sky queries complete, each with two explicit funnel
profiles; six sea queries stop at the native Prepare error boundary. The same two
complete maps and 128-node limit apply. Larger graphs are not truncated.

`review_navigation_dispatch.py` executes native Seeker.RunModifiers against five
explicit prepared lists, with/without callbacks and pass values 0/1/2 (30 cases).
Guarded callbacks record native receiver, path argument, call site and order.
Pass 0 runs the pre-process callback then list PreProcess methods; pass 2 runs the
post-process callback then list Apply methods; pass 1 runs neither in these cases.
The native dispatcher preserves the supplied list order, including a deliberately
reversed list. This is not registration/sort validation: the Apply callbacks here
are observation boundaries, not the actual modifier calculations.

`review_navigation_player_points.py` loads the complete external, hash-pinned
MoveController.lua source and invokes its actual MoveToPosition method on host
Lua 5.4. Twenty cases cover nil/empty/single/multiple points, world/local position,
and immediate-player/asynchronous-nonplayer entry selection. The callback removes
the first point only when more than one exists, then copies the remaining points.
The pipeline also executes this source callback on every successful funnel output.
The source digest is fa020de008d42e2d54c7e10bd75c67b9dbe2aaaba173ddf313b7d4c23646ef30.
No official source is bundled. The managed list/RemoveAt bridge and immediate
callback delivery are explicit host models, and source execution is instruction
bounded. This is not the official Lua runtime, native binding or frame movement.

Both hosts produce byte-identical dispatch and player-source test outputs and pass
49 focused tests, including rejecting unknown source/library digests before use.
The remaining connected-execution gap is native modifier registration/List.Sort,
FunnelModifier.Apply (including its actual settings and lifetime behavior), and
integration of these with the Seeker dispatcher. Prepared initialization and
limited map/profile coverage still prevent final-player-path equivalence claims.
No access or credential block occurred. The three seeds, movement guards and house
entry/exit scope remain unchanged; no app-suite rerun, device/live-server acceptance,
remote CI, push or merge is implied.


## Phase 44: native registration/sort and FunnelModifier.Apply composition

The research pipeline now runs Seeker.RegisterModifier, List.Sort,
ArraySortHelper.Sort/IntrospectiveSort/IntroSort/SwapIfGreater, Comparison.Invoke
and the native modifier Order comparator. Five bounded inventory cases cover empty,
single and both registration orders of the StartEnd/Funnel pair. Both pair orders
produce StartEnd then Funnel. Generic metadata, initialized statics and an existing
cached comparison delegate are explicitly prepared; cold delegate construction,
GC, arbitrary additional modifiers and the live inventory are not validated.

Native Seeker.RunModifiers now drives guarded callbacks which execute native
StartEnd.Apply in the retained search VM and native FunnelModifier.Apply in a
separate prepared VM. StartEnd is replayed from Trace's original center point list
and checked against the independently validated endpoint-modified output. The
native dispatcher enforces the sorted sequence; the callbacks no longer merely
record names. The bridge validates native caller, owner, path argument and order.

FunnelModifier.Apply executes its native part splitting, portal construction,
navmesh/Unity-object checks, list replacement and release sequence. Its call to
Funnel.Calculate crosses a guarded ABI bridge to the already validated native
funnel VM, including native Unity rotation. Object allocation, bounded pool storage,
AddRange copying and releases are explicit models; no path geometry or smoothing
formula is replaced with Python. Allocation/release ownership and the final vector
list are checked. The profile is quality value 0, unwrap enabled, with split false
and true separately; it excludes grid, off-mesh, cross-tile and high-quality
simplification branches. A prepared non-null Unity handle does not prove a real
Unity object's lifetime.

The composed calculation continues through the verified official MoveController
source callback on host Lua 5.4. Across both Python hosts, all 12 synthetic queries,
18 official-map queries and five registration cases produce byte-identical output.
Six synthetic queries complete and six stop at the native error boundary; masks
include land/sea/sky/empty and folded geometry. On the two whole official maps,
12 land/sky queries complete and six sea queries fail because the maps have no
eligible sea nodes. Every successful query runs both split profiles. Native funnel
and player callback point lists remain identical to phase 43. Both hosts pass
50 focused tests, including ambiguous/duplicate modifier inventory rejection.

This closes the register/sort/dispatch/Apply *composition* gap for the stated
fixtures, not full-client equivalence. Runtime state and external dependencies
remain prepared/modeled across VMs; the official Lua VM and managed binding,
cold initialization, actual runtime settings/modifier changes, heuristic/profile
coverage and broader ordinary-map coverage remain unverified. Only M13224 and
M13216 are complete official-map inputs here; 15 other reviewed maps still exceed
the 128-node research bound and are excluded without truncation. Native outputs
are offline binary execution, not captured device/client/server outputs.

No movement authority or seed removal follows from these results. All three
navigation seeds and unverified-path guards remain, houses retain entry/exit only,
and no product runtime changes, full app-suite rerun, remote CI, live-server/device
acceptance, push, merge or release is claimed. No credential or permission block
occurred. The next evidence needed is verified cold initialization/runtime profiles
and expanded whole-map reference coverage, followed by comparison with the actual
production consumer before any removal or enablement.


## Phase 45: cold delegate construction, defaults and eight complete maps

The registration probe now executes the previously absent delegate branch of
Seeker.RegisterModifier: allocation is a guarded zeroed-object model, while the
native Comparison constructor, method-pointer/instance-flag access, cache write,
Invoke and sorting are executed. Ten cold/warm inventory cases check the native
target, receiver, MethodInfo and one allocation for each nonempty cold run. The
composed path chain now starts with the cached delegate absent. Resolved metadata,
class initialization and singleton state are still prepared; this is not full
application cold-start or Unity AddComponent/Awake validation.

The constructor-default probe executes StartEndModifier's complete constructor and
FunnelModifier's constructor/base chain on zeroed objects with prepared static
state. It verifies endpoint modes 3/3, raycasts disabled, layer mask -1; and funnel
quality 0, unwrap true, split-at-every-portal false. A separate AstarPath constructor
prefix stops at its first allocation boundary, after the relevant fields are set.
Audited native field offsets plus native writes establish these constructor defaults:
heuristic value 2, scale 1, maximum nearest distance 100, full nearest search false.
This differs from the research profile (zero-scaled heuristic, full nearest search,
no distance bound). Scene deserialization may override defaults; do not label these
constructor values as verified live-player settings.

Verified RoleController/MoveController source establishes fresh-root creation,
component add/reuse and an initial Land mask. The 36 decoded Lua files inspected
show no explicit heuristic/funnel setting mutation, which is limited corpus evidence.
Serialized scene/prefab AstarPath values and later native changes still need offline
inspection or a controlled runtime capture. No account credentials are needed for
the offline work completed here.

The research search/preparation/portal graph bound is now 256, with unchanged
instruction limits and no product download-limit changes. Before expanding it,
portal-VM connection arrays were moved from 0x60a0000 to 0x6120000: at larger node
counts the former region would overlap the 0x60c0000/0x60d0000/0x60e0000 funnel,
part and output buffers. The new bounded connection region ends at 0x6160000,
inside the 0x6000000..0x6200000 arena. Search uses a separate VM; its 256 PathNodes
and GraphNodes end at 0x6090000 and 0x60a0000, and its connection region ends at
0x60e0000 before the node-class region. The funnel still accepts at most 128 portals;
the composed pipeline rejects searched corridors above 127 nodes without truncation.
A native 256-node search/Trace case exercises the exact graph boundary independently
of the smaller funnel bound. Inputs with 257 nodes remain rejected.

Eight whole official graphs now participate: M13217, M13221, M13223, M13224,
M13225, M13226, M13227 and M13216, totaling 1,338 triangle nodes. Their 72 queries
produce 48 completed land/sky searches and 24 sea Prepare error boundaries (these
maps lack eligible sea nodes). Each completed query exercises both funnel profiles
and the player-source callback. Maximum observed corridor length is 27. Nine other
reviewed ordinary maps remain above the 256-node bound and are excluded, never
truncated. Both hosts produce byte-identical results; outputs on the earlier two
maps remain identical to phase 44. The 40 native search vectors (including the new
256-node trace), ten registration cases and three constructor/default records also
match across hosts. Both hosts pass 51 focused tests.

### Evidence sufficient for data staging versus movement replacement

Official hashes, versions, geometry, connection-edge interpretation and the bounded
native/reference checks support the existing diagnostic/database staging work for
the reviewed assets. They do not establish that all general-map seeds can be removed
or that the production movement consumer is equivalent under actual player settings.
The profile mismatch above is a concrete unresolved issue, in addition to incomplete
map coverage and prepared runtime dependencies. All three seeds and movement guards
remain; no production movement is enabled by these probes.

Further offline work can inspect serialized AstarPath settings, execute verified
heuristic/nearest profiles and expand complete-map references within audited bounds.
Unity object lifecycle, official Lua/managed binding and actual movement behavior
need a device/client integration check. Server acceptance of movement and house
entry/exit needs a controlled live-server check; neither has been performed here.
The app-wide regression baseline is still phase 26, not this research-only change.
No remote CI, push, merge or release is claimed. House scope remains entry/exit only.


## Phase 46: verified scene settings and an explicit Awake override boundary

`review_navigation_scene_settings.py` reads only existing cached scene bundles.
It authenticates the cached MainPackage manifest, checks each scene's declared size,
MD5 and CRC before UnityPy parsing, and records SHA-256 provenance. Each scene is
bounded to 1 MiB and the aggregate to 20 MiB. No downloads or automatic external
reference loads occur. MonoBehaviour script references are resolved only to
MonoScript objects inside those same verified bytes, requiring the exact AstarPath
class, empty namespace and AstarPathfindingProject.dll identity. The GameObject
owner must also resolve locally. Missing/ambiguous profiles fail explicitly.

All 17 reviewed ordinary scenes (1,696,639 compressed bytes total) contain exactly
one locally resolved AstarPath with these serialized values:

| Field | Scene value |
| --- | --- |
| heuristic | 2 |
| heuristicScale | 1.0 |
| maxNearestNodeDistance | 100.0 |
| fullGetNearestSearch | false |
| scanOnStartup | false |
| data.cacheStartup | true |
| component enabled / owner active | true / true |

These are now scene-file observations, not just constructor defaults. They match
the phase 45 constructor values for the shared fields but still differ from the
existing zero-heuristic/full-nearest research profile. Owner active/enabled flags
do not prove effective runtime activation through every parent/lifecycle condition.
The manifest and bundles are specifically **ResourcesPC** assets. Identical results
on desktop/Android Python hosts do not establish the installed Android client's
scene package or runtime settings.

`review_navigation_scene_initialization.py` provides reproducible pinned-source static
evidence: the verified Stage.lua calls CGResource.LoadScene with the model-derived
scene name and Stage.OnLoadStage callback. Its SHA-256 is
784b5098241463159112b29fa81ca23dfa9a2cc24dd3fe20ec29f1a05df52605.
The native AstarPath.Awake sequence reads OnAwakeSettings from static offset 0x20,
skips it when null, and otherwise invokes the delegate at 0x1a78a50 before subsequent
initialization calls. The pinned library and exact instructions are checked. This
is disassembly evidence, not execution of Awake or proof of the delegate's actual
target. No claim is made that all later native/Lua code leaves these fields intact.

Both hosts produce byte-identical scene and initialization reports and pass 53
focused tests, including missing/nonfinite/invalid profile fields and unknown
source digests. This step does not rerun path calculation under the scene profile;
phase 45's route results remain valid only under their stated research settings.
No official scene content or extracted game data is added to the repository.

### Remaining offline work and minimum runtime observation

Offline work can still trace registrations of OnAwakeSettings, inspect additional
platform/version manifests and serialized assets, and implement native path probes
for the verified scene profile. The indirect callback alone is not evidence that
it mutates settings or that runtime capture is the only possible next step.

For a legitimate instrumented test client, the minimum useful runtime observation
is one ordinary scene load with a record immediately after Awake and immediately
before the first path request: client/package version and bundle identity; active
AstarPath identity; the four search fields above; OnAwakeSettings target or null;
Seeker traffic mask/tag penalties; actual modifier inventory/order and settings;
and graph identity. Capture the input positions, raw node/vector path, modifier
output and Lua-consumed point list without enabling unverified LaLa movement.
Repeat on the target desktop and Android clients; record land/sea/sky only when
those modes are actually available. No account password or unrelated account data
is needed in the captured evidence. A supported diagnostic/test build or existing
runtime logs are needed for these internal values; ordinary screenshots cannot
prove them. This environment has no Unity runtime/device acceptance setup.

That capture can validate lifecycle/managed/Lua binding behavior; server movement
acceptance and house entry/exit remain separate controlled live checks. Neither
kind of runtime test has been performed. Three navigation seeds and all unverified
movement guards remain, with house scope restricted to entry/exit. Changes are
local only; no remote CI, full application-suite rerun, push, merge or release.


## Phase 47: callback write candidates and verified local Lua coverage

`review_navigation_awake_writes.py` makes the offline investigation reproducible
from the pinned official library/metadata and the existing private Lua cache. It
finds 481 ADRP/LDR windows referring to the reviewed AstarPath type-info slot and
tracks simple register aliases through bounded 768-byte windows. Three write
instructions to static offset 0x20 are identified and manually checked:

| Address | Reviewed native meaning |
| --- | --- |
| 0x1a79820 | AstarPath.OnDestroy's conditional callback-clear path |
| 0x1b4a330 | AstarPathWrap.set_OnAwakeSettings, non-null delegate branch |
| 0x1b4a350 | Same setter, null/general branch |

The setter begins at 0x1b4a270. It calls ToLua.CheckDelegate at 0x20e7ab4 using
Lua stack index 2, then stores the resulting delegate in the static callback field.
The converter identity was resolved through the official generic-method table
(method definition 16421), rather than assigning the nearest unrelated non-generic
method name. Native method tables independently identify the setter token
0x0600125a in Assembly-CSharp.dll and OnDestroy token 0x0600003a in
AstarPathfindingProject.dll. A setter capable of receiving a delegate is not proof
that the player bootstrap calls it or proof of any particular callback target.

The scan is deliberately a candidate finder: it follows one known type-info slot
and simple straight-line aliases, not complete control flow, all pointer aliases,
reflection, dynamically generated names or arbitrary runtime stores. It must not
be used to claim that these are the only possible writes in the entire application.
The mapped method lookup used during investigation was also not treated as proof
for generic/shared addresses; the relevant candidates were checked separately.

All 36 locally decoded Lua files were revalidated against the pinned official
866-entry path/MD5 index and their encrypted bytes, then decoded again using the
pinned metadata codec with exact re-encryption checks. Decoded cache bytes must
match. Basename plus MD5 resolves same-name entries (notably Function.lua) without
guessing. No literal OnAwakeSettings reference appears in those 36 files. The
remaining 830 indexed files are outside this cached-source audit, and computed
field names are not ruled out. No new files were downloaded or executed, and the
product Lua allowlist was not expanded.

Both hosts produce byte-identical reports (481 windows, three write candidates,
36 verified Lua files, zero literal hits) and pass 53 focused tests. This verifies
repeatable offline analysis, not runtime behavior on an Android device or the
Windows client. The actual registrant, delegate target and setting-override result
remain unconfirmed. There is no evidence here that the callback is non-null in a
normal player session, nor enough evidence to assume it is always null.

### Minimum evidence to resolve the actual target

Further offline resolution needs the applicable bootstrap and remaining official
Lua source content or a statically resolvable registration path; the current cache
is insufficient for a complete source search. The task remained offline.

In an authorized diagnostic/test client, record whether the setter is invoked and,
if it is, the source/function identity of the Lua argument at stack index 2 plus
the converted delegate's target/method identity. At the first ordinary scene's
Awake boundary, record callback null/non-null, each invocation target (including
multiple delegates if present), and the four search settings immediately before
and after invocation. Also record final settings immediately before the first path
request to detect later changes, along with package/scene identity. A null callback
must be recorded explicitly. One such trace per target client/version is the
minimum useful starting point; one session does not establish every traffic mode
or future version. These observations need supported runtime diagnostics rather
than screenshots, and need no shared passwords or unrelated account data.

No such device trace exists in this workspace. Therefore no overridden search
profile, movement equivalence, server acceptance or seed removal is claimed.
The three navigation seeds, unverified-movement guards and house entry/exit-only
scope remain unchanged. Work stays local; no push, merge, release, remote CI or
new full application-suite run occurred.


## Phase 48: scene-profile nearest checks and Lua responsibilities

No user Player.log was available. This investigation therefore uses only pinned
local official bytes and the existing bounded ARM64 emulation. It does not need
login, server connections, process attachment, client modification or recordings.

`tools/review_navigation_scene_nearest.py` reuses the verified PC scene reader
and the pinned graph hashes. On eight whole ordinary maps (1,338 triangles), it
checks three near points in each of land/sea/sky modes: 72 queries. Unlike the
previous full-path research profile, these nearest-node calls use the actual
serialized `fullGetNearestSearch=false` and `maxNearestNodeDistance=100`.
The original unbounded/full-search result is checked independently against
triangle projection, and the scene-profile result is checked for matching
nearest distance/point or legitimate distance/tag rejection. All 72 near-query
results match the original profile on these inputs. This is not a proof for
arbitrary points, callback-modified settings or complete paths.

One far point per map is placed 101 units above the highest mesh vertex.
Models 13217, 13224, 13227 and 13216 reject it. Models 13221, 13223, 13225 and
13226 reach the existing 200,000-instruction VM limit. Their reports explicitly
say `unverified_instruction_budget`; no limit was raised and no rejection or
client failure is inferred. A fresh VM is created after an incomplete execution.
Nine other reviewed ordinary maps remain excluded by the existing 256-node
research bound, without truncation. The report keeps `can_send_packets=false`,
`runtime_overrides_verified=false`, `complete_paths_verified=false` and an
explicit aggregate far-query verification flag.

Reproduction (private inputs are not distributed in the repository):

```sh
PYTHONPATH=/tmp/loader-research:. python -m tools.review_navigation_scene_nearest \
  --libil2cpp /workspace/validation/official-client/libil2cpp.so \
  --manifest-root /workspace/.localappdata/WLRE_LaLa/official_sync/manifests \
  --bundle-root /workspace/validation/navigation-1296/bundles \
  --cache-dir /workspace/validation/navigation-1296
```

### Verified Lua call chain, not a runtime observation

The phase-47 `review_navigation_awake_writes` check was rerun: all 36 cached
Lua files again match the pinned 866-entry index, encrypted MD5 identity,
metadata-based decoding and exact cleartext. None contains a literal
`OnAwakeSettings` reference. This is a partial source audit; 830 indexed files
remain outside this cache and dynamically computed names are not excluded.

Concrete lines in the verified decoded sources:

- `Define.lua:2430`: land/sea/sky tag masks are 9/4/15.
- `Stage.lua:639`: `DoLoadStage` maps `stageData[stageId].modelid` to `M%05d`,
  checks resource presence, and invokes `CGResource.LoadScene` at line 648.
  `ReceiveChangeMap` reads the scene from a packet at line 1410 and calls
  `LoadStage` at line 1457. This establishes one map-load path, not absence of
  every possible offline entry point.
- `MoveController.lua:45`: creates/reuses Seeker and FunnelModifier and sets
  the initial land tag mask. Lines 379-408 check active AstarPath, choose
  immediate player versus deferred non-player search, choose local/world
  starting coordinates, then remove the first returned point when more than
  one exists and copy the rest into `currentPath`.
- `Role.lua:8177`: `CheckPosition` samples a 3-by-3 X/Z neighborhood with
  offsets -0.05/0/0.05 and asks native `LuaHelper.GetNodeTag`. At line 8194,
  `CheckClickPosition` tests the clicked point's tag. At line 8200,
  `CheckCanArrivePos` calls `LuaHelper.GetPath` using the current Seeker tags.
  The Lua therefore performs policy checks and consumes native results; these
  functions do not contain the triangle search algorithm.
- `TrafficController.lua:199`: `SetUser` changes scene layers and position
  sampling for sea/sky traffic; it also selects X-axis facing in water/moon
  scenes. Those layer changes alone do not establish final Seeker tag values.

The pinned official index includes `Lua/Controller/PlayerController.lua`, but
its bytes are not in the current decoded cache. That is a concrete next source
for player initialization/traffic changes, not evidence that it registers the
callback. Scene serialization supplies search defaults; native AstarPath and
modifiers perform graph search and smoothing; the verified Lua controls requests
and consumes their point lists. No final runtime override or Windows-native
behavior has been established. The complete-path harness still uses its earlier
zero-heuristic research profile and is not silently promoted to scene-equivalent.

No recording is required for this offline step. Without a verified map-name to
model mapping and a predicted observable discrepancy, asking the user to record
an arbitrary map would not close the settings gap. Future ordinary-client video
can compare visible routes only, not internal callbacks or exact 3D vectorPath.
Three seeds, house entry/exit-only scope and movement guards remain unchanged.

Validation: both host environments produced byte-identical final scene-nearest
reports (48 accepted near queries and 24 tag-rejected near queries), and each
passed 53 focused navigation/safety tests. The Android parity audit still passes
185 shared core files; the repository audit found no broken local links. These
are host tests, not Windows-client, Android-device, live-server or full-suite
acceptance. Changes remain local, with no push, merge, release or remote CI run.


## Phase 49: verified player traffic-tag source

Fetched only the indexed `Lua/Controller/PlayerController.lua` from
`https://wlreftpsrc.chinesegamer.net/WLN/TW/1.3.23/LuaScripts/Lua/Controller/PlayerController.lua`.
The bounded HTTPS request rejects redirects, requires HTTP 200 and the exact
response URL, and checks the encrypted bytes against the existing pinned official
index MD5 before metadata-based decoding and exact re-encryption verification.
No client Lua was executed and no product decoder allowlist was expanded.
The initial sandbox socket denial was resolved through the supported network
permission mechanism; no proxy/TLS or destination-policy bypass was used.

Encrypted SHA-256:
`fae0333090b7ac4f8e21cbd7f7ffa3ffc550787556133f268dd72144efef3c05`.
Decoded SHA-256:
`0054442ed2d8a5196ea60c497155c8f5f45cd1ec303d01fd4ab6e36e3cccc542`.
Decoded length: 72,754 bytes. These bytes remain in the private validation cache,
not in either application repository.

The new `tools/review_navigation_player_settings.py` validates the index,
cipher identity, metadata and exact reviewed plaintext hashes. It checks the
specific update branch and call sites without evaluating Lua. Source evidence:

- `PlayerController.lua:88` creates the RoleController. The previously verified
  MoveController initialization sets the initial land mask.
- `UseTraffic` starts at line 1619. It creates TrafficController at line 1634,
  then calls `UpdateTraversableTags` at line 1635, before the model-load callback.
- `UnUseTraffic` starts at line 1671. It clears `self.traffic` at line 1680 and
  calls `UpdateTraversableTags` at line 1682.
- `GetTrafficKind` at line 1713 returns land when no traffic exists, otherwise
  delegates to the current TrafficController.
- `UpdateTraversableTags` at line 1735 selects sea/sky/land and assigns the
  corresponding Seeker mask. The independently pinned Define.lua supplies
  numeric values 4/15/9 respectively.

This closes the earlier missing-source link between transport changes and
Seeker tags. It does not establish that a particular live session invoked these
branches or that no later code changes the mask. The new file has no literal
OnAwakeSettings, heuristic, heuristicScale, maxNearestNodeDistance or
fullGetNearestSearch references. It requires RoleController, TrafficController,
ToolController and SmallPetController; the latter two are not in this reviewed
cache. They are dependency leads, not proven callback registrants. No arbitrary
missing Lua files were fetched merely to claim completeness.

Reproduction:

```sh
PYTHONPATH=/tmp/loader-research:. python -m tools.review_navigation_player_settings \
  --lua-root /workspace/validation/official-lua-1.3.23 \
  --metadata /workspace/validation/official-client/global-metadata.dat
```

Both host environments produce byte-identical reports. Separate negative checks
confirm that a one-byte change in the encrypted PlayerController source and a
modified index are rejected. Both hosts pass the same 53 focused navigation and
safety tests. This is static source verification and host testing, not Windows or
Android device acceptance.

### Far-query evidence remains bounded

A private instruction trace of model 13221 resets its counter on entry to native
AstarPath.GetNearest, excluding graph setup. Within the existing 200,000-step
limit it records 1,039 calls to NavmeshBase.GetVertex and NavmeshTile.GetVertex,
then stops at 0x28327c4 inside TriangleMeshNode.GetVertices. The method identities
are resolved from the pinned metadata/native table. This shows substantial
native geometry work on the far query, not a Lua callback wait or network need.
It does not prove termination, native correctness or that raising the limit is
safe. The instruction limit and product safety bounds remain unchanged.

The earlier four verified far rejections remain valid; the other four cases
remain unverified. No additional far-query pass, full-path setting equivalence,
callback override, seed removal or newly enabled movement is claimed. Work stays
local; no push, merge, release or remote CI run occurred.

The complete cached-source audit was rerun after this download: 37 files now
verify against the same 866-entry index, with zero literal OnAwakeSettings hits;
829 indexed sources are still outside that audit. Far-query traces for models
13223, 13225 and 13226 also exhaust the unchanged budget, stopping at 0x2d83840,
0x2832698 and 0x2a98ed0 respectively. Their private traces are evidence of the
limits reached, not successful rejection results.


## Phase 50: bounded Common, Controller and Logic source census

The new offline `tools/review_navigation_lua_batch.py` selects deterministic,
lexically sorted batches from the same pinned 866-entry official Lua index.
It covers all Common (13), Controller (27) and Logic (154, including Protocols)
files, in five batches of 40/40/40/40/34. Each batch is bounded to 40 files and
16 MiB encrypted bytes, each file to 2 MiB; download requests additionally use
15-second timeouts and a 300-second batch deadline. Only the exact indexed
Common/Controller/Logic and Logic/Protocols path shapes are accepted. An initial
path check rejected nested Protocols entries before downloading; the validator
was extended only for that observed indexed subdirectory, retaining traversal
rejection and the pinned index check.

Acquisition reused 20 verified cached files and fetched 174 from the pinned
1.3.23 LuaScripts URL on wlreftpsrc.chinesegamer.net. Redirects, unexpected status
or response URL, oversized responses and wrong MD5s are rejected. No index or
version was silently updated. All 194 files verify against index MD5, pinned
metadata decoding and exact cipher round-trip; total encrypted input is
5,044,544 bytes. Both per-file SHA-256 hashes and literal require references are
recorded in private audit reports. No source code is executed or shipped, and
no product decoder allowlist is enlarged. Files retain their full relative
paths in a separate private cache, avoiding basename collisions and keeping the
older 37-file audit inventory unchanged.

The scanner records case-sensitive literal occurrences (including possible
comments or strings) of OnAwakeSettings, heuristic, heuristicScale,
maxNearestNodeDistance, fullGetNearestSearch, AstarPath, traversableTags,
tagPenalties, FunnelModifier, StartEndModifier, Seeker and the relevant
LuaHelper path/node calls. It is not a Lua AST or runtime analysis. No literal
OnAwakeSettings, heuristic/heuristicScale, maxNearestNodeDistance,
fullGetNearestSearch or tagPenalties reference occurs in these 194 sources.
The AstarPath hits are in MoveController, StageObjController, Role and Room;
the Role.lua:338 occurrence is commented-out source, illustrating why literal
hits are not themselves execution evidence. Existing house scope remains only
entry/exit; Room scan calls do not add house navigation to the product scope.

### A concrete initialization entry point

The verified `Lua/Logic/LuaArtifact.lua` defines `LuaArtifact.Initialize` at
line 116 and contains 98 literal require statements. It invokes UI.Initialize
at line 135, Config.Initialize at 138, Resource.Initialize at 164,
Data.Initialize at 182, Stage.Initialize at 190, Network.Initialize at 196 and
Role.Initialize at 202, then opens the login UI at line 334. This is static
call-order evidence (some work is inside a coroutine), not proof of observed
startup or callback-null behavior. It gives a concrete next chain rather than
assuming an unindexed Main.lua exists.

Across the batch, 546 distinct literal require module names map to entries in
the pinned index under the observed `Lua/<module>.lua` convention. In particular,
Logic/UI.lua contains 228 literal requires and Logic/Data.lua contains 132.
Those dependency lists include sources outside this batch; validating an edge
or parent file does not validate the required module's execution or contents.
Dynamically constructed names, native bootstrap and modules loaded outside this
index remain outside this literal scan.

Reproduction uses the private encrypted cache and does not download anything:

```sh
PYTHONPATH=/tmp/loader-research:. python -m tools.review_navigation_lua_batch \
  --index /workspace/validation/official-lua-1.3.23/index.json \
  --metadata /workspace/validation/official-client/global-metadata.dat \
  --cache-root /workspace/validation/navigation-lua-batches/phase50 \
  --group controllers --batch 0
```

Repeat with `--group logic --batch 0`, then batches 1, 2 and 3. Missing files
produce an explicitly incomplete report; corrupt files or invalid selectors
raise errors. Both hosts produce byte-identical reports for all five batches.
Negative checks verify incomplete-cache reporting, corrupt-source rejection
and invalid group/batch rejection; each host also passes 53 focused navigation
and safety tests.

Coverage must not be conflated: this literal scan covers 194/866 files, leaving
672 outside it. Combined with the prior 37-file source inventory, the unique
verified-source union is 211/866 (655 not yet verified), but the additional 17
older sources were not newly scanned for every term above. No runtime override
absence, complete path equivalence or new far-query result is established.
Three seeds and all movement guards remain. Changes remain local; no push,
merge, release, remote CI or device acceptance occurred.


## Phase 51: complete pinned Lua index and native bootstrap evidence

The batch auditor now covers UI (450), Data (133) and the remaining support
libraries (89), in addition to the phase-50 Common/Controller/Logic sources.
Selection remains from the exact pinned index, with safe relative path segments,
no traversal, at most 40 files per batch, 2 MiB per file and 16 MiB per batch.
The support group is the explicit complement of the other four groups, avoiding
both gaps and duplicate coverage. Empty/out-of-range batch selections are errors.
Acquisition used at most four read-only workers at a time, each running the
previous bounded request flow; neither download nor product limits were removed.
All files retain their indexed relative paths in the private cache.

All 866 indexed Lua files for the pinned 1.3.23 snapshot now verify against the
published MD5 list and pinned client metadata codec, including exact cipher
round-trips. Aggregate encrypted input is 13,550,304 bytes. The 24 batches have
1 controller/common, 4 logic, 12 UI, 4 data and 3 support reports. This establishes
coverage of this particular published Lua index, not every embedded native
string, client variant, later update, dynamically supplied chunk or runtime state.
No source code, metadata, cipher parameters or official client binary was added
to Git or to the shipped product. The previous 37-file research cache is intact.

### Literal and dynamic-reference results

Across all 866 sources there are no literal OnAwakeSettings, heuristicScale,
maxNearestNodeDistance, fullGetNearestSearch or tagPenalties hits. The two
`heuristic` hits are unrelated English comments: ltn12.lua:15 describes global
package export, and socket/http.lua:152 describes HTTP/0.9 recognition. The UI
AstarPath references occur in UI/Logic/UIRoom.lua at 481/482/889; they do not
expand the user-requested house entry/exit-only scope. Data-layer Seeker hits
are in MissionData and NewbieTutorialData and are not evidence of search-profile
assignment.

The scanner additionally records literal loadstring, dofile, loadfile, rawset,
setfenv, getfenv, System.Reflection, Injection and `_G[` occurrences. Eighteen
files have such hits. Manual samples distinguish concrete mechanisms:

- Common/Function.lua:1320 uses rawset for a string-key table helper.
- Logic/PlayerSetting.lua:15 writes the player's settings data table.
- System/Injection/LuaInjectionStation.lua uses an injection metadata pipeline,
  replaces named method entries and installs a metatable __index function
  (lines 33-48). This is a generic mechanism; its presence does not prove that
  navigation uses it in a live session.
- mobdebug, cjson, jit, protobuf and supporting files also contain dynamic
  facilities. Names may occur in strings, comments or library capabilities
  rather than active application code.

These literal patterns are not a complete Lua parser, taint analysis or dynamic
call graph. Concatenated/aliased field names and native/reflection writes are
not eliminated by a zero-match result. No debugger, injection mechanism or
remote Lua facility was activated during this investigation.

### Native file-entry and Initialize dispatch

`tools/review_navigation_lua_bootstrap.py` validates the pinned native binary and
metadata hashes, resolves five metadata literal slots through ELF relocations,
and checks selected exact ARM64 instructions from the inspected full methods.
The native identities were resolved against the same metadata/module method
tables, rather than inferred from nearest-address names.

- Lua..cctor at 0x31005c4 loads literal `LuaArtifact` (slot 0x4965968,
  metadata literal 8501) and stores it in the static field at offset 0x18
  at instruction 0x3100640.
- Lua.InitializeCallback at 0x30ff1d8 constructs a LuaState, opens libraries,
  binds wrappers, adds a search path ending in `/Lua`, and starts the state.
  It concatenates `Logic/` (slot 0x49ace70, literal 8461) with static +0x18,
  then tail-calls LuaState.DoFile at 0x30ff3c8 -> 0x3630400. The default
  source target is thus Logic/LuaArtifact, matching the verified index entry.
- Artifact.Update has a branch at 0x1586098 calling Lua.DoFunction
  (0x30ffab4) with static +0x18 and literal `Initialize` (slot 0x49382e8,
  literal 7220). Another branch uses `Update` (slot 0x4992ed8, literal 13938).
  These establish static dispatch sites, not execution in a live player.

The bootstrap tool explicitly reports runtime_execution_verified=false,
callback_state_verified=false and all_static_writes_verified=false. Its selected
instruction checks are not exhaustive control-flow analysis. No absence of later
changes to static +0x18 or OnAwakeSettings is asserted. Full source coverage
therefore narrows the source gap without turning static evidence into runtime
acceptance.

Re-run the batch command from phase 50 with `--group ui --batch 0` through 11,
`--group data --batch 0` through 3 and `--group support --batch 0` through 2.
The updated scanner also records dynamic-literal hits for the earlier groups.
Native bootstrap reproduction:

```sh
PYTHONPATH=/tmp/loader-research:. python -m tools.review_navigation_lua_bootstrap \
  --libil2cpp /workspace/validation/official-client/libil2cpp.so \
  --metadata /workspace/validation/official-client/global-metadata.dat
```

All 24 final batch reports and the bootstrap report are byte-identical across
the two host environments. Checks verify disjoint full 866-file coverage,
missing-cache incompleteness, corrupt-source rejection and invalid/empty batch
rejection. Both hosts pass 53 focused navigation/safety tests. These are host
and static-source checks, not Windows/Android device or formal-server acceptance.
Four far queries still lack a completed native result within the previous
instruction budget; no new far-query pass is claimed. Three seeds and movement
guards remain, and work remains local without push, merge, release or remote CI.


## Phase 52: dynamic links and completed bounded far-query diagnostics

### What the 18 dynamic-capability sources actually establish

`tools/review_navigation_dynamic_links.py` first revalidates all 866 indexed
sources with the complete batch auditor, then verifies cipher and decoded
SHA-256 again before cross-referencing dynamic symbols. Incomplete corpus input
is an error. It reports direct literal locations, never a claim that aliases,
computed names or native invocations are excluded.

The most relevant concrete findings are:

- InjectByModule appears only at its definition in LuaInjectionStation.lua:63.
  InjectByName appears only in that same file at its internal call (67) and
  definition (72). No other indexed source contains these literal entry names.
- CacheInjectFunction occurs in InjectionBridgeInfo.lua:65 as mapping metadata
  and in LuaInjectionStation.lua:86 as the generic registration call. The bridge
  file has no literal AstarPath, Seeker, Pathfinding, FunnelModifier or LuaHelper
  names. This is not proof against aliases or changes outside the pinned corpus.
- The pinned LuaInjectionBus.lua has only a license comment and a commented-out
  example require. The verifier checks that this particular file has no text
  outside its known block/line-comment forms; it is not a general Lua lexer.
  No injector was enabled or executed for this investigation.
- DebugServerIp occurs only in tolua.lua:15-16, guarding the mobdebug require
  and start call. The condition's value and any native assignment are unknown.
  No debugger, remote connection or runtime flag was enabled.

Other dynamic hits are narrower than their keywords might suggest. Reflection
BindingFlags.lua defines numeric flags and a mask helper, rather than performing
a reflected field write. jit/vmdef.lua contains library-name strings. cjson util
has a generic run_script helper; this alone does not establish a navigation
caller. Common/Function.lua uses rawset for string-key tables; PlayerSetting.lua
uses it for stored player settings. Quaternion/Vector3 cache fields, protobuf/pbc
manage data structures, and misc/strict supplies global-variable checks. These
classifications come from inspected pinned source, not execution or universal
absence proofs. All 18 source identities and dynamic literal locations remain
in the reproducible report.

Reproduction:

```sh
PYTHONPATH=/tmp/loader-research:. python -m tools.review_navigation_dynamic_links \
  --index /workspace/validation/official-lua-1.3.23/index.json \
  --metadata /workspace/validation/official-client/global-metadata.dat \
  --cache-root /workspace/validation/navigation-lua-batches/phase50
```

### Four formerly incomplete far queries now finish under a separate cap

Phase-49 instruction traces showed that the 200,000-step runs were still doing
native geometry work. A new, explicit offline diagnostic permits 400,000 steps
only as a second reviewed option. The default nearest factory still uses
200,000; the full-path `_search_state` factory rejects the extended option.
Unsupported numbers, booleans and non-integers fail before loading the library.
Neither product download/safety limits nor movement authority changed.

`tools/review_navigation_far_completion.py` accepts only the four pinned model
IDs and graph hashes, at most 256 triangles, the reviewed non-XZ-only profile,
land mask 9, full nearest search false and distance cap 100. A query point is
101 units above the highest vertex, so every point of every mesh triangle is
at least 101 units below it. The script executes the original native routines
under the existing address guards; it does not substitute a Python rejection.
An instruction hook starts counting at outer AstarPath.GetNearest, excluding
graph construction. Every VM is fresh for its model, and the hard 400,000 cap
still returns an explicitly unverified result if exhausted.

All four original far points now return native node=None at the normal return
sentinel 0x601f000, within the diagnostic bound:

| Model | Triangles | Native query instructions | Native vertex calls |
| --- | ---: | ---: | ---: |
| 13221 | 212 | 241,769 | 1,272 |
| 13223 | 232 | 261,283 | 1,392 |
| 13225 | 188 | 210,397 | 1,128 |
| 13226 | 250 | 279,473 | 1,500 |

The earlier 200,000-step reports remain correct historical incomplete results;
they are not overwritten or relabeled as passes. The new results close those
four particular offline far-query cases, not arbitrary far points, live-client
settings, full vectorPath equivalence or server acceptance. The other four
far rejections from phase 48 remain unchanged.

```sh
PYTHONPATH=/tmp/loader-research:. python -m tools.review_navigation_far_completion \
  --libil2cpp /workspace/validation/official-client/libil2cpp.so \
  --cache-dir /workspace/validation/navigation-1296
```

Both hosts produce byte-identical dynamic-link and far-completion reports.
The focused regression suite now has 55 passing tests on each host, including
new gates rejecting unsupported budgets and extended budgets in path pipelines.
Android parity still verifies 185 shared core sources. Full runtime callback
state, indirect native writes and the complete path harness's earlier heuristic
profile remain unresolved. Three seeds, house entry/exit scope and all movement
guards remain. No push, merge, release, remote CI or device acceptance occurred.


## Phase 53: complete path fixtures under serialized scene parameters

The full-path research harness can now explicitly select the reviewed scene
profile instead of only the earlier zero-heuristic baseline. This is a research
input option, not a production movement change. The default remains heuristic
mode 0 with scale 0, full nearest search and no distance limit. The scene option
uses the verified serialized values: mode 2, scale 1, full nearest search false,
and maximum nearest distance 100. Only reviewed heuristic modes 0 and 2 are
accepted. Before native Initialize, the harness reads back the prepared Path
heuristic/scale fields and fails if they differ from the requested values.
No native calculation is replaced with a Python implementation.

`tools/review_navigation_scene_paths.py` revalidates the official scene manifests,
bundle size/MD5/CRC and graph hashes, then compares both profiles for one endpoint
pair in each land/sea/sky mode on each of eight complete reviewed ordinary maps.
The nine other reviewed ordinary scenes remain excluded by the existing
256-triangle graph bound, without truncation. Each successful search still passes
the independent Bellman-Ford cost and route-edge checks before native endpoint,
portal, modifier and funnel processing and pinned MoveController point-list
handling. Both previously reviewed split-at-every-portal options are retained;
neither is claimed to be an observed live-player setting.

There are 24 input queries, executed under both profiles (48 native pipeline
runs). In each profile, 16 land/sky cases complete and eight sea cases reach the
expected native no-route boundary. Two sky queries change their route and final
point list despite equal independently verified minimum costs:

| Model | Mode | Baseline cost | Scene-profile cost | Funnel points, split=false |
| --- | --- | ---: | ---: | --- |
| 13226 | sky | 55,870 | 55,870 | 5 -> 6 |
| 13227 | sky | 46,819 | 46,819 | 4 -> 4, with different coordinates |

The split=true point lists also differ in these cases. This is concrete evidence
that the old research profile must not be silently treated as scene-equivalent,
even when a cost-only check passes. Both profiles' results remain in the report
for reproducible regression comparison. It does not establish which profile a
live session has after callbacks or other runtime mutation.

```sh
PYTHONPATH=/tmp/loader-research:. python -m tools.review_navigation_scene_paths \
  --libil2cpp /workspace/validation/official-client/libil2cpp.so \
  --libunity /workspace/validation/official-client/libunity.so \
  --manifest-root /workspace/.localappdata/WLRE_LaLa/official_sync/manifests \
  --bundle-root /workspace/validation/navigation-1296/bundles \
  --cache-dir /workspace/validation/navigation-1296 \
  --move-source /workspace/validation/official-lua-1.3.23/decoded/MoveController.lua
```

### Exact Lua binding for OnAwakeSettings

The bootstrap verifier now also checks the native wrapper registration evidence:

- The OnAwakeSettings name is metadata literal 9419, referenced by slot
  0x499d6b8 inside AstarPathWrap.Register (0x1b4b6d8).
- Slot 0x4942a18 resolves to method definition 4650,
  AstarPathWrap.get_OnAwakeSettings, token 0x600122b.
- Slot 0x494e5c0 resolves to method definition 4697,
  AstarPathWrap.set_OnAwakeSettings, token 0x600125a.
- The register block constructs LuaCSFunction delegates at 0x1b4d0c8 and
  0x1b4d0f8 and calls LuaState.RegVar at 0x1b4d110 with that name and the
  getter/setter pair. Exact pinned instructions and decoded metadata references
  are checked by the tool; full-method disassembly supplies the surrounding
  register dataflow.

This closes the binding identity gap: the setter previously found by the native
write scan is exposed as the named Lua variable. Registration is capability,
not evidence of assignment. No setter invocation, non-null delegate target or
post-Awake setting override has been observed, and the report explicitly keeps
setter_invocation_observed=false and callback_state_verified=false.

### Remaining evidence boundary

The current environment has pinned Android-native functions, PC scene resources
and a bounded synthetic VM state, not the official Unity/Lua application startup
and scene lifecycle. Neither two matching Python-host reports nor complete
indexed Lua text coverage supplies actual runtime callback state. The smallest
missing runtime evidence is an authorized same-version test client's ordinary
scene initialization trace: callback null/non-null and invocation target, search
settings after Awake and immediately before a path request, plus the resulting
final point list for fixed inputs. That would require a supported/authorized
test environment with instrumentation; an ordinary-client recording or missing
Player.log cannot provide these fields. No account credentials, debugger
activation or client/security modifications were requested or performed.

Both hosts produce byte-identical final scene-path and extended bootstrap
reports and pass 55 focused navigation/safety tests. These are the same pinned
Android native routines running in two host environments, not separate Windows
and Android installed-client acceptance. The previous far-query diagnostics
remain valid; no full-suite, live-server or device acceptance is claimed.
Three seeds, house entry/exit-only scope, all movement guards and local-only
branch restrictions remain; no push, merge, release or remote CI run occurred.

### Phase 54: isolated shadow comparison and bounded offline coverage

Added `navigation_shadow.compare` and `python -m tools.compare_navigation_shadow
--map ID --start X Y --end X Y --travel-mode land`. The service consumes an
already loaded runtime and cached database; official preview always receives
`download=False`. It has no session or packet sender, exports diagnostic XY
points rather than a movement route, and marks all results `can_send_packets=False`.
The standalone CLI still checks CDN metadata through `prepare_dynamic_runtime(sync=False)`;
it does not download navigation bundles, observe a live player, or continuously
check CDN revisions. It is not an entirely offline command.

Live callers can supply runtime/state getters. Changes in runtime, stage snapshot,
scene, role or navigation revision discard both sides. Stale navigation and house
navigation are rejected. Existing legacy coordinate guards remain; an additional
stage-field comparison binds legacy metadata to the supplied official snapshot.
Missing caches, mismatched provenance, missing prohibition markers, invalid points
and excessive output become explicit diagnostic errors. Houses retain existing
entry/exit behavior; this tool does not participate in either operation.

Neither exact XY equality nor equal costs establishes correctness: legacy shared-edge
geometry ignores official travel tags, heights are not compared, runtime obstacles
are not applied, and preview search is not the full official player pipeline.
There is no automatic acceptance threshold, UI integration or production movement
activation in this change.

Current CDN manifest audit at catalog
`b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6`
found 972 ordinary models / 1,333 stages: 770 within declared download budget,
202 missing or ambiguous scene assets, and 17 reviewed models. These are manifest
candidates, not 972 validated navigation graphs.

For reproducible **offline historical** sampling, run
`python -m tools.review_navigation_shadow_samples --snapshot DIR --output REPORT.json`.
DIR supplies `current-identity.json` and `current-stages.json`; versioned navigation
caches must already exist. This does not claim the snapshot is the current CDN
version. Each of 17 reviewed ordinary models is tested in land/sea/sky modes,
with at most five evenly spaced walkable node indices and ten pairs per mode.
At the pinned catalog above: 51 model/mode rows, 302 attempted pairs, 292 previews
and 10 explicit no-route rejections. Sixteen model/sea combinations have no
walkable nodes and therefore no sampled pairs; they are not counted as passes.
35 packet-coordinate shadow requests yielded 8 complete comparisons (2 exact XY
matches) and 27 incomplete comparisons. Legacy errors were 24 missing-model
cases and 2 stage mismatches; official preview rejected 1 disconnected case.
These checks validate cache loading, output guards and selected path invariants,
not official runtime equivalence. Desktop and Android statuses and point sequences
agree exactly; accumulated XY lengths differ by less than 6e-11 packet units
between host Python environments (not a navigation acceptance tolerance).

Both hosts pass 64 focused tests (9 new shadow tests plus 55 existing navigation
checks). Full application suites, Windows client, Android device and live-server
acceptance were not rerun. All three bundled navigation seeds and movement guards
remain. Actual OnAwakeSettings execution and final player settings still require
runtime evidence unavailable in this environment; this diagnostic feature does
not resolve that gap. Changes remain local, with no push, merge or release.

### Phase 55: explain incomplete comparisons without weakening guards

The previous 27 incomplete results have now been traced to source data:

- 24 requests (land/sky on M13216 through M13227): neither legacy
  `graph_origins.json` nor the navigation archive catalog contains the model.
  Their legacy stage dimensions are also 65535/65535 with zero small-map offsets,
  whereas the current official stages have concrete dimensions/offsets. The
  earlier mapping exception hid this additional drift. Both causes are now
  reported. Substituting official geometry into the legacy side would destroy
  the independence of the comparison and is deliberately not done.
- 2 requests on logical stage 12050: old model 15129 versus current model 12050.
  Legacy model 15129 exists, but that does not establish equivalence with 12050.
  The report records each differing field and both values; no seed is patched.
- 1 request on stage/model 58001, land: source node 952 reaches only 952 and 953;
  target 3777 is unreachable. Boundary targets 856 (tag 1), 341 and 494 (tag 2)
  are excluded by the reviewed land mask 9. An independent unweighted traversal
  confirms the preview result. This is an expected mode-filtered graph rejection,
  not a crashed parser or evidence of official live-client behavior.

`ComparisonUnavailable` now reports legacy provenance gaps separately from
unexpected errors. `NoPreviewRoute` remains a `NavigationError` subclass for
existing consumers and carries source, target, reached count and travel mode;
shadow output labels it `no_route`. Overall comparison remains incomplete when
one side has no path; no equality or success is fabricated. The offline sample
reviewer checks every no-route rejection with independent unweighted reachability,
records exact packet inputs for replay, and no longer catches arbitrary
`ValueError` as an expected no-route result.

Both hosts: 69 focused tests pass; 302 offline route pairs still yield 292 previews
and 10 independently checked graph disconnections. The same 35 shadow requests
still yield 8 completed and 27 incomplete comparisons, now with explicit causes.
Tests cover combined metadata/missing-origin gaps, changed model IDs, typed
no-route outcomes and rejection of a falsely claimed disconnected graph.
No runtime semantics or movement authorization was expanded. Three seeds remain.
The user's running LaLa 7.3.0 is not established to contain these unpushed local
commits and is not acceptance evidence for this feature. No device/live-server
acceptance, push, merge or release was performed.

### Phase 58: same-geometry controls for all 27 incomplete cases

User-reported Windows execution of the 8dbbb02 offline kit matched all 343 file
hashes and the expected 17-model, 292/10-route and 8/27-comparison counts, with no
movement packets reported. This is user-reported offline Windows execution, not
our direct observation, official client output, or live-server acceptance. The
new checks below were subsequently run on Linux hosts; they are not in that kit.

Added `tools/navigation_same_geometry_control.py`, called by the bounded sample
reviewer for each incomplete comparison. Both algorithms receive the exact same
verified official cache and packet-coordinate conversion. The unfiltered old
shared-edge algorithm is compared with the mode-filtered official preview graph.
This is explicitly an algorithm control, **not a replacement historical baseline**.
It does not populate or alter any of the three legacy seeds.

A separate FIFO label-correction algorithm independently checks minimum cost and
reachability without using the preview priority queue. It has a fixed two-million
arc-examination cap and fails explicitly if exceeded. It verifies the preview
cost, but does not claim native player settings or optimality under unknown live
rules. The largest observed workload was 10,799 arc examinations.

Both hosts produced 27 controls: 26 preview paths with independently confirmed
minimum costs, and one confirmed disconnection (58001 land). The unfiltered
algorithm produced 27 paths, but 12 traverse nodes or edges forbidden by the
preview graph. These are land cases 13217, 13218, 13219, 13220, 13221, 13222,
13223, 13225, 13226, 13227, 12050 and 58001. Fifteen unfiltered paths are allowed
by the preview graph. Of the 26 pairs with both paths, 12 have identical face
sequences and 14 differ. These are diagnostic facts, not movement acceptance.

Original historical comparison counts remain 8 complete / 27 incomplete:
24 lack historical geometry and have stale dimensions/offsets, 2 refer to a
changed model ID, and 1 is a normal preview graph disconnection. No historical
source can safely be invented to change these counts. The 26 usable official
paths now have additional independent validation instead of being discarded
because the old baseline is unavailable.

Desktop and Android each pass 72 focused tests. New synthetic checks exercise a
late cheaper path requiring FIFO revisits, work-budget refusal, unreachable
nodes, target penalty accounting and a geometrically shared edge absent from
the official connection table. Reproduction uses the existing
`tools.review_navigation_shadow_samples --snapshot DIR --output REPORT.json`;
additional evidence is in each incomplete result's `same_geometry_control`.
There is no live movement integration, new download, seed removal, push or merge.

### Phase 59: close implicit legacy movement authorization

Restored worktrees were clean at desktop d554c48 / Android 59afcc8, still on
`codex/official-bootstrap-migration`. No push or main merge was performed.

Inspection found an actual production gap: Movement.start rejected only explicit
`can_send_packets=False`, while legacy Coordinates.route omitted that key.
Thus legacy geometry could reach locomotion despite its existing
`live_movement_verified=False`. The 12 unfiltered control paths demonstrate why
implicit authorization is unsafe. Movement.start now requires both flags to be
exactly True, and Coordinates.route explicitly returns can_send_packets=False.
Missing flags, false values and integer lookalikes are rejected before packet
coordinate conversion or activation. This intentionally pauses unverified
general-map automatic movement (including NPC walking/roaming through this
entry point). It does not enable the new preview for movement or repair the
legacy topology. House entry/exit is outside this navigation-only change.

Tests that isolate scheduling/NPC orchestration now explicitly supply synthetic
route authority; this exists only in tests and is not evidence for real maps.
The minimap double-click integration test now verifies refusal of real legacy
Coordinates output and no emitted movement packets. Runtime-expiry locomotion
is still tested with explicitly authorized synthetic geometry.

`tools.review_navigation_movement_guard --report PHASE58_REPORT --snapshot DIR
--output REPORT` reloads hash-verified official caches, regenerates the 12 actual
unfiltered problematic paths, and checks Movement refuses every one without
calling packet conversion or returning a movement packet. It uses synthetic
player state and never creates a network session. Both hosts passed all 12.
It is a regression reproducer for this pinned corpus, not a live test driver.

Desktop full discovery: 1,851 tests, OK with 169 skips (14.089 seconds).
Android full discovery was **not successful**: 1,530 tests, 13 errors / 3 failures
/ 90 skips, with Kivy attempting a read-only /home/agent/.kivy and local IPC socket
creation unavailable in the default sandbox. Xvfb is also absent. These results
are retained in the private phase59 logs, not reclassified as passing. Focused
navigation, authority, house scope, NPC and automation checks passed: desktop 94,
Android 93. Android's focused run set KIVY_HOME to a writable workspace location.
No Android device or new Windows execution of this patch has occurred.

Runtime evidence remains unavailable: command discovery found no Wine, adb,
Unity, /dev/kvm or /dev/dri. The pinned phase53 bootstrap evidence still explicitly
states setter_invocation_observed=false, callback_state_verified=false and
runtime_execution_verified=false. Ordinary installed LaLa or official-client
video cannot reveal these internal settings. A supported/authorized official
client test environment is needed to capture, for the same resource identity:
(1) OnAwakeSettings null/target/invocation, (2) actual post-Awake and pre-request
heuristic, scale, nearest-distance, tag mask and penalties, (3) exact map/start/end
and height/mode, and (4) the final post-modifier vectorPath and rejection outcome.
Do not ask users to supply passwords or to enable undocumented debugging or
modify the official client. Without such access, no honest procedure for that
internal observation has been established here.

A controlled live-server movement trial is therefore **not ready**. Its future
prerequisites are matching runtime observations, full-path parity, explicit
user-operated test scope and an observation/stop procedure. The current branch
has no verified production route authority and must not send trial movement to
work around that missing evidence. All three legacy seed BLOBs remain until the
replacement covers required ordinary maps and production acceptance is proven.

### Phase 60: all-mode directed graph and bidirectional acceptance matrix

The user-side read-only inventory reports Windows Data/Main Package 1296 matching
our historical sample, with the official game stopped and no logs, symbols or
diagnostic facility found. This confirms a package-version match only; it does
not observe post-Awake callbacks or actual path requests.

Added `tools.review_navigation_mode_matrix` with `--snapshot DIR --controls
PHASE58_REPORT --output REPORT`. It loads exact-key hash-verified caches, independently
constructs allowed node sets using explicit reviewed tags (land 0/3, sea 2,
sky 0/1/2/3) and walkability, and checks every directed arc against serialized
connections and shared geometry. It compares the resulting full graph with the
preview graph before testing routes. Model/cache mismatch, graph mismatch,
incorrect costs, forbidden route edges or the independent solver's work-budget
exhaustion stop the audit; none is counted as an ordinary no-route result.

Coverage: 17 ordinary models / 9,075 geometric nodes / 51 model-mode rows.
All node eligibility and allowed directed arcs were checked. The fixed sample
of up to five nodes per row is now tested in both directions, with the independent
FIFO minimum-cost solver for every query (604 queries):

| Mode | Allowed nodes | Allowed arcs | Valid minimum-cost routes | Confirmed unreachable |
| --- | ---: | ---: | ---: | ---: |
| Land | 2,164 | 4,362 | 272 | 20 |
| Sea | 1,462 | 2,996 | 20 | 0 |
| Sky | 8,274 | 23,452 | 292 | 0 |

Sixteen sea rows have no eligible nodes and are explicitly reported as such,
not as successful route coverage. This is complete graph-eligibility checking
for these 17 caches, not all-pairs routing or all 972 ordinary model candidates.

All 12 previously forbidden old-algorithm cases were traced to excluded travel
tags. There were no missing serialized arcs or missing shared edges along those
reported paths. Excluded-node occurrences by map: 12050=26, 13217=3, 13218=8,
13219=8, 13220=10, 13221=6, 13222=4, 13223=2, 13225=9, 13226=9, 13227=1,
58001=124. Therefore the current mode-filtered preview is doing substantive route
planning with independently verified cost/eligibility; the production refusal
guard is not being presented as the replacement navigation implementation.

Synthetic tests cover all four known tags, disabled walkability, an unknown tag
that must not become sky permission, asymmetric costs, and separation of a
missing serialized arc from a travel-tag exclusion. Focused suites pass desktop
97 / Android 96; both offline matrix reports match exactly. Full application
suites were not rerun for this diagnostic-only addition; prior Android full-suite
environment limitations remain. No new Windows execution or live-server test is
claimed. Both previously delivered offline ZIPs remain unchanged.

Confirmed: pinned geometry, serialized connections, reviewed fixed tag rules,
per-node penalties and zero-tag-penalty graph optimum for sampled endpoints.
Unconfirmed: whether actual scene startup changes those defaults, final native
GetNearest/modifier behavior for all scenes, runtime obstacles, the player's
actual traversal state, and server acceptance. Package 1296 matching alone cannot
supply those observations. No guards were relaxed, no seeds removed, and no
live movement, push, merge or release was performed.

### Phase 61: observed Bangkok corner and source-derived waypoint following

The supplied frame review corrects (2835,4052) to t=8.466667 s; t=8.5 s is
(2826,4060). Eight observations from 8.2 through 8.8 s are pinned in
`tools/review_navigation_corner_following.py`. The current movement/traffic mode
is not visible and is not assumed. All eight positions locate on node 21,
flags 524289 (walkable bit set, tag 1), excluded by land mask 9. Distances to the
ideal planar land route decrease from 19.55 to 16.48 packet-coordinate units;
nearest eligible land-boundary distances decrease from 14.54 to 4.95. Thus this
is a continuous observed deviation, not a single mistyped sample. These are
spatial measurements; timestamps do not reveal internal path vertices.

Verified MoveController Lua SHA-256
`fa020de008d42e2d54c7e10bd75c67b9dbe2aaaba173ddf313b7d4c23646ef30`
contains a waypoint-following step before movement: lines 113-125 select squared
threshold 0.01 for EMoveSender.Server and 0.16 otherwise, advance while squared
2-D distance is strictly below the threshold, then aim toward the next point.
Lines 152-157 clamp movement to direction length or horizontalSpeed*deltaTime;
lines 205/230 use CharacterController.Move. Static source supports early corner
switching, but does not prove the branch, frame times or collisions in the video.
At the established coordinate scale, the two radii are 10 and 40 displayed units.

The new diagnostic implements a bounded **Python model** of this step, not Lua
or Unity execution. Fixed sensitivity inputs are 30/60/120 FPS, speed 350 packet
units/s and radii 10/40; no parameters are fitted to the video. No collision,
gravity or hidden runtime path modifications are modeled. Comparing spatial
polylines to the eight samples gives:

| Radius | FPS | Maximum observed-to-model distance |
| ---: | ---: | ---: |
| 10 | 30 | 16.45 |
| 10 | 60 / 120 | 13.12 |
| 40 | 30 | 4.18 |
| 40 | 60 / 120 | 8.12 |

The 40-unit model explains the direction and much of the size of corner cutting,
including entering a region excluded from the original land graph. Residuals
remain larger than coordinate rounding; do not infer FPS, sender, traffic mode,
actual vectorPath or collision behavior from the improved fit. Model final
positions are reported instead of silently snapping them to the requested goal.

Optional pinned native test extracts the exact 24-face / 26-vertex corridor
chosen by our land preview and remaps only those nodes into the already bounded
FunnelModifier.Apply harness. Native portal construction and funnel produce the
same four points: (4836,5154), (3680,3980), (3010,3870), (1850,4915), with maximum
packet-coordinate error below 0.001. This is native Android ARM64 code in modeled
VM/pool/list state, not Windows execution or official graph selection. It does
not extend the 256-node complete-search harness: Bangkok's full 513-node search
was not run. No evidence that the official video used this corridor is implied.

Reproduce with `python -m tools.review_navigation_corner_following --snapshot DIR
--move-source PINNED_DECODED_LUA --output REPORT.json`, optionally supplying both
`--libil2cpp` and `--libunity` for the native corridor check. External official
code is hash-pinned and not copied into the repository. Invalid inputs, work
budget exhaustion and native mismatches fail rather than adjusting the model.
Both hosts produce matching reports; related tests pass desktop 100 / Android
99, including strict-threshold, no-overshoot and fixed-work-budget cases. No
production motion algorithm, masks, movement authority or seed changed.

Next evidence needed is actual waypoint switching/character movement around the
corner, including sender, traffic mode, per-frame position and CharacterController
result. Existing video establishes a spatial deviation but cannot expose those
fields. Do not resolve the deviation by allowing tag 1 for land, removing obstacles,
or treating a source-derived approximation as official runtime validation.

### Phase 62: confirmed walking; execute waypoint following in pinned Lua

The user confirms the Bangkok recording was walking. We therefore retain land
mask 9; the tag-1 segment is no longer explained by presumed air traffic.
Walking still does not reveal EMoveSender, exact frame times, callbacks or physics.

Static source tracing strengthens the normal local-input branch evidence:
PlayerController.MoveToStage ends by calling RoleController.MoveToPosition with
EMoveSender.Player and isPlayer=true (line 478). PlayerController.MoveToPosition
forwards its supplied sender; RoleController forwards it to MoveController
(lines 506-542). Define enumerates Player=1, Server=3, AutoWalk=6 (352-362).
PlayerController.Appear sets WalkSpeed (325), Define sets WalkSpeed=3.5 (807),
and RoleController.SetMoveSpeed calls MoveController.SetDefaultSpeed.
MoveToPosition copies defaultSpeed into horizontalSpeed. These source defaults
are not proof of the observed session's input branch or later overrides.

`tools.review_navigation_lua_motion --move-source PINNED_LUA --output REPORT`
now executes the actual hash-pinned MoveController.Update source in host Lua 5.4,
using supplied currentPath, grounded walking state and speed 3.5. Vector functions
and CharacterController.Move are explicit stubs: Move applies displacement without
collision. No official Lua/native binding or Unity physics equivalence is claimed.
The source itself performs threshold selection, point removal, direction/step
calculation, Move invocation and completion/reset. Host OS/file/module access is
removed, source bytes are pinned and bounded, and instruction/frame/output caps
fail closed. Official Lua content remains external to the repository.

Nine fixed cases (Player/AutoWalk/Server x 30/60/120 FPS) passed on both hosts.
Player and AutoWalk have identical results with the 40-coordinate-unit radius;
Server uses 10. Actual Lua traces match the prior Python translation within
1.5e-10 packet-coordinate units. This confirms the translation under the supplied
stubs, not the gameplay environment. The 40-radius observed-corner residual is
still 4.18-8.12; no tuning or mask relaxation was performed.

An additional comparison assumption must remain explicit: (1850,4915) is the
observed final stopped position, not a captured requested target/vectorPath end.
Under the supplied four-point path, Player/AutoWalk models stop at approximately
(1863.57,4903.18), (1875.13,4893.24), or (1877.34,4891.33) for 30/60/120 FPS.
Do not snap these to the recorded endpoint or claim a match. Target coordinates,
completion callbacks and collision handling remain unobserved. RoleController's
OnMoveDone invokes a supplied callback and clears its move target; the callback's
actual observed-session behavior has not been captured.

Collision evidence: MoveController creates/reuses a Unity CharacterController,
sets stepOffset=0.4 and performs CharacterController.Move for grounded walking.
Its UpdateCharacterControllerSize derives radius/height/center from the character
model, and RoleController supplies those model values. A tag-1 navigation region
is therefore not itself proof of an impassable physics collider: waypoint
selection and actual collision movement are separate stages. The actual character
model dimensions, collider geometry/state and Move displacement result are still
needed to confirm the physical trajectory. Do not invent these values.

Related suites pass desktop 102 / Android 101. Two new guards reject unreviewed
or oversized Lua before execution; the actual nine-case source runs also pass.
No production movement was changed or enabled, no legacy data removed, and no
new Windows/live-server test, push, merge or release occurred. Current safe
progress is an independently reproduced source-following mechanism; complete
runtime equivalence remains unproven.
