# Dynamic navigation: verified boxes, costs and UI previews

Phase 24, 2026-11-06. This extends [the navigation database work](OFFICIAL_NAVIGATION_DATABASE.md).
The three legacy navigation seeds remain. Formal movement is not switched to the
new database: dynamic obstacle geometry is still incomplete. Both product UIs now
expose a read-only official database preview, with an explicit movement guard.

## Scope change after phase 24

Player-house navigation and furniture obstacles are now explicitly out of scope.
The historical research below is retained as evidence, not a remaining completion
requirement. Product navigation rejects houses while tent entry and exit remain
supported. General maps and version-matched routing remain the migration target.

## Actual collision source and rescan behavior

The official MainPackage manifest places Furniture_9515 and Pillar_9194 in
`mainpackage_model_house.bundle`, 38,765,382 bytes. A separate research download
used a 48 MiB ceiling, whole-file MD5/CRC validation and SHA-256
`6f5646b1f3a5449e603c019225137129c55741c01ff0e8f47fcabec769581b9b`.
The product navigation download limit is still 32 MiB / two bundles; this research
does not silently increase it or put the house bundle into startup downloads.

The complete house bundle has 836 BoxColliders. The reviewed subset is two boxes
under the L/R branches of Furniture_9515 and one L-branch box in Pillar_9194.
`tools.review_house_colliders` follows the exact serialized prefab hierarchy and
reconstructs all eight corners with parent translation, quaternion rotation and
scale. It outputs **prefab-root-local** coordinates, preserving the root transform
separately. Unknown bundle fingerprints, external hierarchy references, cycles,
unsupported collider types and animated hierarchies fail closed. Decoded output
must remain outside Git; no official model data is added to the application.

The collider GameObjects are on layer 19, while the house Recast settings use
layers 21–25. Ignoring them based on the prefab layer would be wrong: current
StageObjController.UpdateModel dynamically adds RecastMeshObj to every L/R box,
sets solid=true and mode=UnwalkableSurface. UpdateActive selects L for direction 1
and R for direction 0, aliases the sides if only one exists, and calls Scan.
SetObstacle toggles the RecastMeshObj components and scans again. Room furniture
and pillar handlers also scan after removal or movement-related updates.

The inspected house graph enables collider and terrain rasterization, disables
mesh rasterization, and uses characterRadius=0.5, cellSize=0.2, walkableHeight=2,
walkableClimb=0.5 and maxSlope=30. These are source evidence, not a substitute for
the actual Recast scan algorithm. Placement additionally raycasts a floor and
applies baseOffsetY; stacked furniture may change elevation. A model's prefab
corners alone do not establish its world-space obstacle or usable clearance.

Verified StageObjController.lua ciphertext SHA-256:
`c9fb613c6d840bbf1f72b4ccce4b5ffa54a2f8cbbf9aff63b291d87bf1459ae1`.
Its plaintext was obtained from the same verified official Lua index and retained
privately; no executable/key material is shipped.

## Costs and bounded planar smoothing

Read-only native inspection confirms Path.GetTraversalCost (`0x2d95a34`) adds the
target node penalty and selected tag penalty for the default traversal provider.
TriangleMeshNode.Open (`0x2833724`, additions at `0x2833840`) combines that with
parent cost and the serialized connection cost. Seeker construction allocates a
zero-filled 32-entry tag-penalty array. Custom traversal providers, special endpoint
cost overrides and later character-specific overrides remain unsupported.

PreviewMesh now uses Dijkstra over the directed, walkability/tag-filtered graph,
with serialized arc cost plus the target node penalty and zero tag penalties.
Its reported cost starts at zero (no origin-node penalty constant). Overflow beyond
UInt32 is rejected. This is the reviewed default cost model, not a claim to emulate
every live Path subclass. A test with two geometrically tied corridors proves the
lower serialized-cost corridor is chosen; asymmetric costs and penalties are tested.

Optional planar funnel smoothing supports at most 512 same-height corridor
triangles. It validates unique shared portals, finite endpoints and nondegenerate
faces, then independently clips every output segment against the triangle corridor.
The union of clipped intervals must cover the entire segment. Slopes and unsupported
corridors fail explicitly; the implementation does not flatten a nonplanar surface
or claim equivalence to the client's full FunnelModifier unwrapping/quality modes.

Across selected pairs in the nine actual models, 217 smoothed routes passed
containment, retained the same graph cost and were no longer than midpoint routes.
Another 33 were rejected as nonplanar and 35 had no permitted land-mode connection.
These are static geometry checks, not live-server movement or obstacle acceptance.

## Product entry points and lifecycle

* Desktop: existing navigation window → **官方資料庫預覽**.
* Android: role overview → **官方導航預覽**.
* Both offer database-only preview or explicit selected-map sync and preview,
  a travel mode, and optional planar smoothing. They show source and packet XY
  preview points but have no action that sends them to the game.
* The shared PreviewJob allows one worker per dialog, performs work off the UI
  thread, and expires results when runtime identity, player/scene, navigation
  revision, stale flag or house context changes. Closing a dialog drops results.
* Cold start without the active official runtime reports that resource sync is
  required. Missing/unknown map data does not fall back to another DB version.
* Movement.start explicitly rejects routes whose can_send_packets flag is false.
  The legacy movement route is retained until dynamic behavior is verified; the
  new preview cannot accidentally be promoted through a consumer callback.

The CLI additionally offers `--smooth-planar`. UI validation errors persist until a
new submission, and stale results are cleared. Desktop Tk and Android Kivy host
smoke tests cover rendering, preview-only submissions and disposal; these are not
APK or physical-device tests.

## Remaining concrete work

1. Verify all required furniture/pillar models and ItemData model-selection fields,
   including stacking, floor raycasts, active use state and model substitutions.
2. Obtain independently checkable world placements and reproduce Recast collider
   rasterization, radius/height/climb filtering, contour generation and updates.
   The two local prefab box reconstructions do not establish this.
3. Validate nonplanar funnel unwrapping, endpoint handling, live travel-mode policy
   and any custom costs against the matching official client behavior.
4. Extend model coverage and only then migrate formal movement and remove seeds.
   No scan-complete flag or movement authority is inferred from a successful UI
   preview, collider extraction, downloaded bundle or database transaction.

Validation for this local stage: desktop full regression passed 1,793 tests
(3 skipped). Android's isolated host regression passed all 194 files, reporting
1,471 tests (4 skipped). The two UI tests and shared movement-rejection test are
included. Both hosts independently produced the same 217 accepted / 68 rejected
actual-model route outcomes. No APK, device, release or remote CI validation was
performed for this stage.
