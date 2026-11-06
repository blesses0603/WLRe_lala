# Navigation database: verified subset, preview only

2026-11-06 follow-up to [bounded extraction research](OFFICIAL_NAVIGATION_RESEARCH.md).
This is a partial migration. All three navigation seeds remain required by existing
live movement/UI consumers; this change does not replace those consumers or enable
new movement packets. The shared database preview consumer and CLI run on desktop
and Android Python cores. Android device/APK/UI acceptance has not been performed.

## Implemented

`navigation_sync.sync_model` obtains one selected reviewed model from the current
verified MainPackage manifest, checks the official version before and after, and
fetches at most two complete bundles totalling 32 MiB. This ceiling includes cached
bundle sizes and is deliberately conservative. No full-scene dependency loader is
modified. The dependency name is only a candidate: membership in the manifest and
an exact serialized CAB/path-ID TextAsset reference are mandatory. Both bundles
must pass size, MD5 and CRC verification. There is no fallback to an arbitrary URL,
partial bundle or another version after failure.

`astar_cache` recognizes only six reviewed cache SHA-256 fingerprints and A* 4.3.60.
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
reviewed complete catalog identity. The route uses geometric distance, not the
client's serialized costs or all traversal/tag policies, and reports that fact.
It always reports `can_send_packets=false`. No existing live-movement path is
switched to it. Dynamic player-house IDs without an explicit resolved stage are
rejected rather than assigned the smallest house.

Run after core official data preparation:

```console
python -m tools.preview_official_navigation --map 10298 --sync
python -m tools.preview_official_navigation --map 10298
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
one new stage, 500 old synthesized player-house IDs absent from the official table,
and 13 changed model/dimension rows. Twelve of those have changed map-height
inversion values. The 500 IDs require real room-floor context, not static copies.
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
