# State ownership foundation

Sources: `wlre/core/state_ownership.py`, the ownership/snapshot methods in
`wlre/core/state.py`, and the ownership regressions in
`tests/test_automation_integration.py` and `tests/test_state_event_routing.py`.
This is an offline foundation, **not the migrated game State**.

## Covered contract

- The creating thread owns state access and mutation. Snapshots can only be
  created by that thread, then safely consumed by any thread.
- The eleven service-to-field grants exactly match the Python source, including
  shared inventory grants. Unscoped owner writes represent coordinator writes.
- Inner service scopes replace the outer grants, then restore them on normal
  exit or exceptions. Completed writes are not rolled back on service failure.
- Every nested mutation checks the current scope against the original root
  field, even when the caller kept a handle from before the scope was entered.
- Maps, lists, tuples and supported scalar values form a closed immutable data
  tree. Factory inputs are copied; arbitrary reference payloads are rejected.
  Snapshots share immutable nodes, never caller-writable storage. Later writes
  publish a new tree and cannot affect previously published snapshots.
- Tuples cannot have members replaced directly. Maps/lists contained inside a
  tuple can still be edited under the tuple's root field authority.
- Scope disposal rejects wrong-thread and out-of-order calls without changing
  authority. Repeated correctly ordered disposal is harmless.

`OwnedState` is constructed on its writer thread. Use `state.Editing(owner)` in
`using` or the synchronous `state.Write(owner, action)` decorator equivalent.
Neither may span an `await`. `state.Edit(field).At(key).At(index)` yields a checked
path handle; `Value` returns immutable data. Publish `state.Snapshot()` to readers.
Constructing a new `OwnedState(snapshot.Fields)` intentionally gives the current
thread an independent copy; it does not transfer an existing owner's authority.

## Explicit limits and intentional adaptations

- No world-state defaults, event reducers/dispatch, service integration,
  position cache, networking, scheduling, UI or credentials are implemented.
- Map keys are strings with ordinal equality; map enumeration order is not a
  Python dictionary insertion-order contract. Future position-cache and other
  order-sensitive ports must preserve their own explicit order.
- Scalars support null, text, booleans, integral/floating/decimal numbers and
  `BigInteger`. Arbitrary Python objects, mutable byte arrays, cyclic graphs,
  generic object conversion, and serialization are not implemented.
- List operations include replacement, append/extend, insert, remove-at,
  reverse and clear. Indexes follow C# non-negative rules, not Python negative
  or clamped indexes. Slices, in-place multiplication, sort callbacks, map
  `setdefault`/pop/update and the complete Python container surface are not ported.
- Handles resolve the current field tree. They do not expose stale mutable
  subobjects after a field replacement. Owner reads are checked too, which is
  stricter than Python's raw public field reads.
- `Extend` materializes additions before publishing. A failing input iterator
  adds nothing, matching Python `OwnedList.extend` (which materializes its
  guarded comprehension before calling `list.extend`). It is not a transaction
  over arbitrary side effects performed by caller-written iterators.
- A snapshot is deeply immutable instead of Python's detached but mutable plain
  dict/list copy. Callers edit a new owner or create immutable values; they do not
  edit a snapshot in place. Snapshot acquisition and each collection edit are
  owner-thread operations, not synchronization/transaction primitives.

## Source callers to preserve during later ports

This key/order audit is concrete follow-up work, not a claim that all callers
already fit the foundation:

- `wlre/services/items/inventory.py:35` stores bag slots with `str(index)`;
  `wlre/services/items/reservations.py:39,59` likewise normalizes reservation
  slot keys. Those existing inventory keys fit the string-key contract.
- `wlre/services/star_ark.py:259,272,283,289,291` uses numeric planet/agent/event
  keys in `State.star_ark`. Lines 429-433 retain numeric item IDs in the pending
  `bag_expected` and `bag_before` maps. Those callers require a typed integer-key
  extension or an explicit, tested schema adapter before they can be migrated;
  silently stringifying their keys is not existing behavior.
- `wlre/core/state.py:117-123` evicts the oldest position through dictionary
  insertion order. A later position-cache port needs an explicit ordered cache.
  `StateValue.Map` alone must not be used to approximate that eviction rule.

## Verify

From the repository root:

```sh
python3 dotnet/Lala.Core.Tests/State/generate_state_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~StateOwnershipTests
```

The retained Python implementation generates grants for every dataclass field
and a nested-scope/error/foreign-thread trace with its resulting snapshot.
C# tests consume that evidence and additionally verify immutable input/output
boundaries, all exposed mutation operations, invalid-operation atomicity,
scope-token safety, and independently owned state initialized from a snapshot.
No live account, server, external resources or UI is used.
