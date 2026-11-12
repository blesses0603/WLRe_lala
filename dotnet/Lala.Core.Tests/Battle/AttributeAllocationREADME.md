# Offline attribute-allocation receive state

`AttributeAllocationSnapshot`, `AttributeAllocationContext` and
`AttributeAllocationReducer` port only `defaults` and `apply_event` from retained
`wlre/services/battle/attribute_points.py`. The existing typed S8-1/2/3
`AttributeSetEvent`, S8-4 `AttributeAllocationSuccessEvent`, and wrapped/direct
S5-3 `PlayerCombatDataEvent` are reused. No protocol layouts are changed.

## Receive contract and source order

- State starts with pending, acknowledged and uncertain false, null expected and
  sent-at, and an empty status. Receive events never create a pending allocation.
- An imported pending record requires an S8-4 acknowledgment and equality of
  every expected integer statistic before it completes. Current missing keys do
  not equal zero. Extra current keys are irrelevant. Names compare ordinally.
- The explicit context is the numeric `knowledge.player.stats` projection at
  `apply_points_event`, after `apply_live` has consumed this same observation.
  It is **not** the older `State.attributes` buffer, which local dispatch updates
  later. Neither event values nor the buffer substitute for that context.
- The reducer does not update player knowledge itself. The caller supplies the
  context at the correct point in the source order. No ready flag, role, phase,
  event entity, attribute kind or sign restricts the comparison in this observer.
  Any attribute-set event can trigger it, including a remote or companion event.
- Matching values without acknowledgment remain pending. Acknowledgment without
  matching values remains pending. Unrelated events do not trigger comparison,
  including other live-data events. Duplicates and late packets are not filtered;
  after pending becomes false, all receive observations leave it unchanged.
- Source quirks are preserved: null/empty expected maps pass vacuously after an
  acknowledgment; completion clears pending/acknowledged/expected/sent-at but
  does **not** clear an imported uncertain flag. A non-pending uncertain record
  cannot be repaired by late receive packets. This port adds no expiry behavior.
- Imported expected/current integer values use `BigInteger` without spending
  validation, clamping or narrowing. The wire still retains its actual source
  widths. Immutable maps, records and caller-owned context preserve old snapshots.
  This is a numeric-stat projection, not a general Python-object serializer.

## Verification

```sh
PYTHONPATH=/tmp/daily-assistant-deps python dotnet/Lala.Core.Tests/Battle/AttributeAllocationGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~AttributeAllocation
python -m unittest tests.test_attribute_points tests.test_state_event_routing
```

The deterministic Python oracle runs real `State.apply` with a pinned empty
synthetic catalog. Its wrapper calls the retained allocation observer and captures
its exact context, verifying that local attribute buffers still contain the old
values. No allocation/begin/expire/command code is invoked. The **80 sequences,
2,098 snapshots and 120 malformed observations** cover ACK/value arrival order,
duplicates, late observations, absent/empty expectations, unrelated events,
uncertainty, unknown keys, case distinctions, signed uint32 values, wide S5 data,
large imported integers, null timestamps and every incomplete prefix/trailing
extension of the relevant layouts. All 99 focused C# tests pass. Each historical
snapshot and the explicit context are checked for mutation; contract tests also
exercise concurrent immutable reductions and null API boundaries.

At this standalone slice on base `986ca88`, the complete Release Core suite has
**17,362 passing tests**, the unchanged lifecycle suite has **59 passing tests**,
and the retained Python attribute-point/routing suites have **14 passing tests**.

Fixture regeneration is byte-identical. JSON is encoded through the shared
`TestSupport/gzip_json_fixture.py` deterministic byte-array convention, with no
base64 or generated fixture data in the CLR user-string heap. Source hashes use
only single-pass byte CRLF-to-LF normalization; BOMs, malformed UTF-8, bare CR,
non-newline edits and nonrecursive CRCRLF behavior are covered.

## Excluded work

No spending baseline checks, preview validation, allocation construction, begin,
timeout/expiry, command routing, sends, planning, catalog activation or inferred
server success. No `AccountSession`, lifecycle, UI or Android changes. The subsequent
[shared receive integration](../State/ServiceKnowledgeAllocationREADME.md) supplies
updated player knowledge to this reducer in source order. No live-server,
resource, device or transport acceptance is claimed.
The module is not fully migrated merely because its receive observer is ported.
