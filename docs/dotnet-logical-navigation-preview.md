# Offline logical-map route preview

`OfflineLogicalNavigationPreview` composes the retained Python
`navigation_preview.PreviewRepository.route/load` behavior over caller-supplied,
already decoded inputs. It adds the missing logical map → stage/model → mesh-local
route → fractional logical XY conversion without duplicating pathfinding.
`PreviewNavigationMesh` still owns walkability, directed serialized costs, target
penalties, travel tags, height disambiguation, and optional funnel smoothing.

## Public boundary

- `OfflineNavigationIdentity` carries a **claimed** manifest key and data version.
  This is the Python identity / internal `ManifestIdentity.Key` schema, **not**
  `OfficialCatalogObservation.CatalogKey`. Matching supplied strings demonstrates
  compatibility only, never provenance or authorization.
- `OfflineNavigationStages` owns immutable `StageDataRow` values in the supplied
  original binary order. Pass `StageDataParser.Parse(bytes).Values` directly,
  without sorting or re-enumerating through an unordered dictionary. At most
  20,000 rows are consumed, and duplicate IDs fail closed.
- `OfflineNavigationCacheEntry` owns identity/model/origin metadata and references
  an existing immutable sealed `PreviewNavigationMesh`. Its scene ID must exactly
  equal `M` followed by the five-digit model ID. Each entry supports the mesh's
  selected travel mode. Supply separate prebuilt meshes for other modes.
- Stage, cache, and requested repository identities must match in both fields.
  Missing exact models/modes/versions never fall back. `Load` only selects an
  existing supplied entry and applies the house/model guard. It performs no I/O.
- `Route` returns an `OfflineLogicalNavigationRoute` containing the reused mesh
  route and immutable `LogicalPoints`. Coordinates preserve fractions; no rounding,
  clipping, packet encoding, or waypoint execution takes place.

The fixed reviewed coordinate key remains
`b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6`.
The production instance-order pin remains
`1f1bd5ad718542a8469812a5cdabc12155a24ac01fdac6e2dc2506d82c3c41dd`.
There is **no public trust override or review-registry override**.

All outputs are historical observations: `IsHistorical` is true;
`SourceProvenanceVerified`, `AssetsReady`, `CanSendPackets`,
`LiveMovementVerified`, `NetworkCoordinatesVerified`, and
`RuntimeObstaclesApplied` are always false. `InputNavigation` retains the immutable
snapshot used for this calculation; it is not a current runtime lease. The nested
legacy `NavigationRoute`'s official-source/connectivity labels describe the reused
algorithm, not authenticated origin. The composition labels its source as
`caller_supplied_offline_navigation_preview` explicitly.

This feature does **not** port database loading/import, reviewed model/raw-cache
digest validation, downloads, resource admission, dynamic geometry rebuilding,
the asynchronous job's scene/revision/role freshness lifecycle, packet sending,
movement control, UI, server interaction, or account credentials.

## Source semantics retained

1. Reject an unreviewed coordinate key, then reject house scenes, then reject a
   stale snapshot only if its scene equals the **requested** logical map.
2. Prefer a direct stage row. Only a missing row in 61501–62000 uses aliases.
   Alias validation hashes compact JSON of the original stage ID order, then
   allocates rooms starting at 61501 for rows with nonzero `MaxMembers`.
   Collisions with original stage IDs and allocations above 62000 reject the
   whole request. Typed byte fields enforce member/capacity bounds.
3. Block scenes 10000/10298/10299 and 63501–65500; independently block models
   10000/10004/10005. Verified house context does not unlock indoor routing.
4. Use map height as the Y offset, except 65535 maps to 6992. Convert
   `(X,Y)` to `(X*10-origin.X, (offset-Y)*10-origin.Z)`, and invert each route point
   using `((p.X+origin.X)/10, offset-(p.Z+origin.Z)/10)`. `origin.Y` does not enter
   this transform. Optional start/end heights remain unchanged mesh-local Y.

## Bounds and verification

Coordinates, origin, and transformed coordinates must be finite and within the
existing signed Int3 domain. This intentionally strengthens the Python facade's
finite-only check; bounded fractional coordinates remain accepted. The composition
accepts already constructed meshes rather than raw geometry streams, so their
earlier caller-side construction is outside this boundary. Supplied meshes are
limited to 10,000 faces and 100,000 serialized arcs each. Repositories accept at
most 256 entries, 100,000 total faces, and 1,000,000 total arcs. Enumeration stops
at the first excess item; cancellation throws without returning partial results.

`generate_logical_navigation_vectors.py` executes **real retained Python**
`PreviewRepository.route`, `load`, `PreviewMesh`, and `instance_aliases` with a
cache-only synthetic `load_cache` result. File/database/socket access is blocked
during each oracle call, and `download=False` is explicit. Ordinary synthetic
fixtures claim the fixed coordinate key but do not prove trusted source data.
Alias success fixtures privately substitute their synthetic order digest in
Python and the C# internal test constructor. Public production-pin rejection is
tested separately. No genuine positive reviewed-order fixture is available, so
these tests prove the alias algorithm and guards, **not** official-data parity.

The differential suite covers fractional/nonzero origins, zero and sentinel map
heights, mesh height hints, smoothing, modes, no-route errors, direct alias-range
precedence, same/different-scene stale snapshots, house guards, instance order,
collisions and the exact 500-alias limit. C# safety tests add ownership, identity
and model mismatch, invalid/overflowing coordinates, budgets, cancellation and
historical no-send assertions. A no-friend public consumer exercises successful
composition plus production alias rejection and mismatched/stale failures.
