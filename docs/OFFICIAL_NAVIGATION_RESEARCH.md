# Official navigation research: bounded standalone cache extraction

Historical phase-21 status: research only, 2026-11-06. See [phase-22 database progress](OFFICIAL_NAVIGATION_DATABASE.md) for subsequent implementation. The three navigation seeds remain required:
`navigation_data.zip`, `graph_origins.json`, and `stage_coordinates.json`.
No production download quota, navigation consumer, or movement authority changes.

## What the approximately 800 MB figure means

The smallest full Unity scene dependency closure among 775 scene entries was
M12600: 87 bundles, 825,658,853 bytes; after existing cached files, 800,256,441
bytes remained. This is a full scene with visual resources, not a minimum size
for its navigation cache. No 800 MB environment hard limit was found. The
existing runtime's 32 MiB / 24-file budget is a product safeguard and remains
unchanged. The generic bundle fetcher also has a 256 MiB single-bundle ceiling.
The environment had approximately 29 GB free during inspection. No rejected
network request was bypassed and no credentials or access controls were changed.

The manifest had no independently named navigation asset. Inspecting two small
complete scene bundles revealed an AstarPath object's `data.file_cachedStartup`
reference to a TextAsset in a listed dependency. We fetched only the two complete
referenced dependency bundles, verified them through the existing official
manifest MD5/CRC path, and matched BOTH serialized CAB file and object ID.
We did not load a complete Unity scene or claim its other dependencies resolved.

Official MainPackage: `1296_2026_11_04_13_36_07_72`, data version 1.3.23.

| Model | Root bundle bytes | Referenced dependency bytes | Cache bytes | Triangles |
| --- | ---: | ---: | ---: | ---: |
| M10001 | 36,419 | 5,174,162 | 9,257 | 282 |
| M12600 | 43,778 | 5,577,684 | 15,507 | 513 |

Total fetched for these samples: 10,832,043 bytes in four bundles. Scene roots
were bounded to 1 MiB total; the dependency fetch experiment to 12 MiB total.
No partial HTTP response was treated as a checksum-verified full bundle.

M10001's external CAB is `CAB-2e5f635a7d92492b3cd11085d1e7d040`, object
`-5788657058253960011`; M12600's is `CAB-7965e005af08ae86fd7a9eac854a420b`,
object `-4368270071059153749`. The cache SHA-256 fingerprints are recorded in
`wlre/services/world/astar_cache.py`. Raw official files and decoded game contents stay
outside the repositories under the private validation directory.

## Reader evidence and verified scope

Read-only disassembly of the official APK's ARM64 `libil2cpp.so` established:

* AstarData.LoadFromCache at `0x2a92868` reads the referenced TextAsset bytes and
  calls DeserializeGraphs (`0x2a93170`).
* NavmeshBase.DeserializeExtraInfo (`0x27a8c84`) reads tile dimensions, triangle
  indices, two Int3 vertex arrays for the observed version, and node records.
* GraphSerializationContext.DeserializeInt3 (`0x22c69c4`) reads three Int32s.
* TriangleMeshNode.DeserializeNode (`0x2834560`) calls GraphNode.DeserializeNode
  (`0x2d94308`), which reads penalty/flags, followed by three vertex indices.
* RecastGraph.CalculateTransform (`0x2839f44`, overload `0x2839fc4`) uses bounds
  center/size. Both samples have zero rotation. World/graph vertex differences
  independently confirm `(center - size / 2) * 1000` within Int3 rounding.

Inspected binary SHA-256:
`7798c9aaa6986ee200deacf9816a5d2f17a606944aa4a56dd06bfa1acb344636`.
Both caches identify A* version 4.3.60, one RecastGraph, one tile, and no NodeLink2
links. `meta.json` contains a bare dotted System.Version token; the research
reader recognizes only this exact 4.3.60 syntax and preserves source bytes.
It does not apply a general JSON repair or guess another version's layout.

The two decoded geometry objects compare equal to the corresponding complete
legacy mesh JSON objects, including vertices, triangles, raw node metadata and
consumed byte counts. Their derived origins also compare equal. Maximum vertex
transform residuals are 0.055 and 0 Int3 units respectively. This comparison is
corroboration, not the sole source of the binary layout.

[A* serializer documentation](https://arongranberg.com/astar/documentation/dev_4_3_7_a4a6edc5/astarserializer.html)
explains the archive's settings and graph-specific binary separation; it is an
older version and is not sufficient evidence for this build's byte layout.

The two graph-reference members are preserved and hashed but NOT interpreted.
Raw serialized node flags are not asserted to be live graph flags. Runtime cuts,
connections, off-mesh links, other tiles/rotations and packet movement have not
been validated. The tool explicitly reports `can_send_packets=false`.

Official same-version `Stage.lua` and `StageData.lua` were also downloaded,
index-MD5 verified, decoded and round-trip checked in private research. Stage's
TransferMapPosition uses scale 0.01 and mapHeight, with 65535 selecting 6992;
TransferPosition uses the inverse Z direction. Furniture coordinates have a
separate transformation. Full stage coverage and special-house behavior still
need cross-validation before retiring `stage_coordinates.json`.

## Proposed production contract (not implemented here)

1. Resolve a selected model from the current verified scene catalog. Fetch its
   complete root within the existing 32 MiB update budget and resolve AstarPath's
   cache reference by serialized file identity and path ID, never filename alone.
2. Resolve the referenced file only within the root's verified manifest dependency
   list. Cap a data-only import to four bundles and 32 MiB total, including failed
   attempts; reuse only cache entries verified against the same manifest. Reject
   unknown identity, ambiguity, oversized candidates, or exhausted limits.
3. Fetch complete source bundles and validate hashes/CRC before parsing. Restrict
   extraction to the referenced TextAsset's bounded ZIP. Do not change generic
   full-scene dependency traversal or silently strip dependencies from scene loads.
4. Validate supported serializer layout, bounds, GUID, all counts, index ranges,
   exact byte consumption, and coordinate mapping. Unknown versions remain pending
   explicit review, with a diagnostic and untouched original bytes.
5. Stage normalized geometry, origins, mapping and provenance in a versioned DB
   transaction; activate only a complete validated snapshot. Preserve the previous
   usable version on failure. Cold start without valid data must show unavailable,
   never activate fabricated geometry or issue movement commands.
6. Before removing seeds, extend verified coverage to all needed models and stage
   variants, validate consumers and routing semantics, and test both platforms'
   cold start, update failure, rollback and cache invalidation behavior.

Current review tool deliberately accepts only the two known cache fingerprints.
It is not yet a general automatic updater. No further user authorization is needed
for the bounded research described here; no environment policy blocked it. The
remaining work is implementation and evidence coverage, not an 800 MB download
permission request. All changes remain local; no push, release or CI claim.
