# Runtime crafting material inspection

`AccountRuntime.InspectCraftingMaterials(ushort itemId, int batchCount)` captures
one exact `PublicationSnapshot` under the runtime gate and calculates outside it.
The caller supplies only the product and batch count, never a catalog, role or
inventory snapshot. No cached resource fallback is used.

`CraftingMaterialAssessment.Basis` retains that exact historical connection,
receive attempt/revision, state and catalog join. It is not a current-at-return
promise. `Outcome` reports `NoPublication` (including stopped receive attempts),
`CatalogsUnavailable`, or `RoleIdentityUnknown`, in that order, with null
`Preflight`. A known role ID of zero remains known. The original offline helper's
null-owner/null-role equality is unchanged.

`Evaluated` means only that the existing bounded material helper ran. Inspect
`Preflight.Blocker`, needs and allocations for its result. The helper's `Success`
means its material query passed, not permission to craft. The assessment has no
success/readiness flag; `ResourceHeld` is always true and `CanSendCommands` false.
The helper retains the exact crafting, bag and room-storage observations, including
pending/uncertain fields. Source recipe and allocation bounds remain unchanged.

Python `wlre/services/items/crafting.py` separates `recipe_plan`/material helpers
from the command wrapper. This API does not implement the wrapper's pending,
uncertain, battle, event or coordination gates. It does not reserve materials,
alter queues, clear pending work, acquire credentials, prepare resources, send
packets or construct a command plan. Batch validity and recipe blockers retain
the existing helper's precedence. Revocation/reconnect changes later assessments;
previous results retain their old basis only as history.

## Offline validation scope

The runtime fixtures use real framed receive processing, ephemeral loopback
listeners and existing synthetic Unity/SQLite resource fixtures. Their existing
private trust-bit simulation tests wiring only, not official provenance or
production admission. The retained unique product is closed, so those fixtures
verify a real `ProductClosed` material result, not a craftable official recipe.
They cover missing publication/catalogs, known zero identity, exact source
references, catalog revocation, unsupported schedule uncertainty, retirement,
reconnect/rebind and historical results. Synthetic direct-inspection snapshots
separately cover missing identity and preservation of imported pending/uncertain
evidence. A separate synthetic recipe/catalog/state projection verifies complete
material allocation, shortage, invalid batch bounds and null-role helper parity;
it does not modify the runtime's catalogs or claim receipt of an open recipe.
These fixtures are not claimed to be received pending commands. Loopback peers
reject any extra command packets. Existing offline helper vectors cover material
allocation and null-role semantics. The no-friend public consumer calls the new
API on an inert runtime and after cancellation, with no credentials or resources
acquired. No Desktop UI, real-server acceptance or command authority is added.
