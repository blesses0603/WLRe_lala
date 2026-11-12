# Read-only crafting material preflight

`CraftingMaterialPreflight.Evaluate` ports the bounded, coherent-input calculation
prefix of retained Python `crafting.recipe_plan`, before packet construction. It
does not implement crafting execution, local-plan editing, queue mutation,
reservation acquisition, pending settlement, completion, tick/continuation, UI,
transport, or live-resource admission. A successful result is not permission to
craft. Both the context and result expose `CanSendPackets == false`.

## Public contract and authority

`CraftingPreflightContext.FromRuntime(RuntimeRecipeCandidate)` reuses the existing
joined `RuntimeRecipe(SmithRecipe, OpenUsed)` data. It does not accept a bare Smith
row and invent ItemData openness, activate a catalog, or weaken provenance gates.
The runtime candidate remains offline, unverified and unadmitted. The explicitly
named `FromCallerSuppliedRows(ImmutableArray<RuntimeRecipe>)` supports synthetic
and imported offline calculations and labels that origin separately. Neither
origin is production authority. No account-runtime or held-resource path changes.

The context uses one immutable catalog snapshot. Product lookup excludes all
ambiguous products, matching `RuntimeRecipeCandidate.Products`; multiple official
recipe IDs for a product remain valid catalog observations but cannot be selected
by guessing. The 35-byte Smith parser's `RecipeId` is the official identity.
`CandidateRowKey`, product ID, row order and version number are never substituted
for it. Empty or all-unkeyed rows mean the legacy identity layout.

The result retains the exact recipe context, role observation and immutable
crafting, bag and room-storage snapshots used, including pending, uncertain,
readiness, revisions and serial evidence. It reports the selected recipe/tool,
aggregated needs and allocation rows with source, slot, count, current `Before`
balance and bag serial. Cupboard allocations have no serial. Failure exposes no
partial allocations. A material shortage additionally identifies the first
unsatisfied material and remaining quantity.

## Source semantics within the supported input domain

- Gate order is recipe lookup, read-only, ItemData openness, batch count, design,
  time/limit, room/tool, schedule readiness/capacity/duplicate product, bag
  readiness/reliability, room-storage pending/uncertain, then materials and bag
  allocation count. `Output` does not multiply the requested batch count.
- Furniture `ItemOrder` is authoritative. The last active (`Status == 0`) row for
  each item ID wins, not the highest slot; retained rows do not override active
  rows. Workbench is not tool identity. Only stored Owner is compared with role,
  not CurrentOwner. Python's absent-owner == absent-role equality is retained as
  a calculation, **not proof of ownership**.
- Active furniture 39050 raises queue capacity from three to five. Furniture
  39814 permits duplicate products; the queue comparison uses product ID, not
  recipe ID. Crafting Pending/Uncertain are retained observations, not extra
  helper gates. They, battle/event/coordination and authoritative account identity
  still require independent command-wrapper checks.
- Duplicate material rows aggregate in first-material order. For each material,
  numeric ascending bag slots are consumed before numeric ascending cupboard
  slots. Bag locked/enhanced/magic-spar/beat items are excluded. Cupboard rows do
  not inherit bag quality checks.
- Availability preserves reservation counter subtraction and zero clamping via
  the existing reducers. All exclusive/uncertain holds lock, even at zero
  remaining quantity, as do legacy projection slots. Nonexclusive foreign holds
  may pass this calculation and later fail reservation acquisition. Nothing is
  reserved here. Negative imported reserved counters are not silently repaired.
- Each slot is visited once per aggregated material, capped at 255 for bag or
  65,535 for cupboard. Oversized balances are not divided into repeated rows.
  `Before` is current Count, never the original wire record's byte-sized Count.
  Cupboard readiness/reliability is relevant only if bag stock is insufficient;
  storage-wide Pending/Uncertain blocks even an empty-material recipe.

## Explicit typed and oracle boundaries

This is not a complete `recipe_plan` or packet-builder parity claim. One coherent
immutable catalog makes a selected/current catalog drift scenario unrepresentable.
Late active-catalog replacement/mixed-layout errors and current-vs-selected row
drift are excluded, as are `build_add_packet` and `write_cupboard` validation.
For example, an imported cupboard slot zero can calculate successfully while the
packet builder would reject it. A calculation must never be used as a send gate.

Batch count is an `int`, checked against 1..255. Python booleans, arbitrary-size
integers, missing properties and arbitrary dynamic dictionaries are not public
inputs. Context construction validates its separate import contract: at most
20,000 rows, known product IDs, at most five positive material rows, no null or
default material arrays, no mixed identity layouts, and no zero/duplicate official
IDs or contradictory candidate keys. These failures occur at construction, not
at Python's late runtime-catalog stage. Openness is mandatory in RuntimeRecipe.

Imported snapshots must have matching dictionary keys/embedded slot IDs and a
complete unique furniture order. Negative item balances, null/default collection
shapes, more than 256 hold groups or 65,536 hold rows, or overlong projection arrays
are unsupported and fail closed. Bag/cupboard insertion order is not required for
this query because numeric sorting is source behavior. Lock observations are
indexed once to avoid scanning every hold for every cupboard row. No live state
is modified by this optimization. Arbitrarily large cupboard balances and
reservation counters remain `BigInteger` observations.

The retained-Python generator executes the actual `recipe_plan`, `tools`,
`tool_for` and reservation availability helpers on synthetic state. The legacy
Writer constructor and official `build_add_packet` entry are intercepted with a
sentinel before writing any packet bytes. The real helper computes allocations
and performs its coherent recipe-to-product identity check first. Source hashes
pin the helper dependencies; synthetic item naming avoids live catalogs. The
generator verifies its inputs were not mutated. It does not call the command
wrapper, acquire reservations, run timers or access an account/server.

154 retained-helper cases cover source gate precedence, both identities, furniture
order, queue rules, duplicate material aggregation, numeric slot order, quality
filters, reservation locks, counters, current before/serial evidence, storage
states, per-slot caps, all 256 byte-valued bag slots and 96 seeded scenarios.
Directed tests separately cover unsupported imports, huge cupboard balances,
partial-failure discard, snapshot retention, actual offline runtime composition
and unchanged admission gates. The no-friend public consumer exercises the API
and verifies no holdings or queue entries are created.

```sh
python dotnet/Lala.Core.Tests/Inventory/generate_crafting_preflight_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~CraftingPreflightTests
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
dotnet run --project dotnet/Lala.Core.PublicContract.Check/Lala.Core.PublicContract.Check.csproj -c Release
```
