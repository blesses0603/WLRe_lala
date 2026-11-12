# Offline NPC shop evidence

This slice ports all 133 retained lines of
`wlre/services/world/npc_shop_evidence.py`: defaults, the bounded receive observer,
and offline classification. It does **not** enable buying/selling, verify an
order, confirm a payment, or authorize a retry or subsequent command. Protocol
1262 has no verified server transaction identifier. Even `observed_consistent`
is only a correlation of independent observations and still requires manual
reconciliation on the real client/server.

## Integration contract

`NpcShopEvidence.Observe` accepts existing typed `ServerEvent` observations and
an explicit `NpcShopObservationContext`. That context must contain the packet
counter and **post-local-handler** `BagReceiveSnapshot` and
`SessionGoldSnapshot` for this exact event. Run the ordinary local inventory and
gold reducers first. In particular, invalid bag updates and gold-limit/overflow
observations must already have invalidated their reliability flags. The observer
does not apply those handlers, increment the packet counter, guess revisions,
validate provenance, or infer reliability from the packet itself.

- Capture only `bag_snapshot`, `bag_add`, `bag_delete`, `bag_sell`,
  `gold_snapshot`, `gold_delta`, `gold_limit`, `shop_purchase_result`, and
  `sale_notice`. All other typed observations return the same snapshot.
- Record `Ready && Reliable` independently for inventory and gold. Neither alone
  establishes trust. Missing item index is retained as null; index zero is not
  replaced by a guessed slot.
- Keep the latest 96 relevant events in original observation order, not sorted
  packet order. Each relevant event increments the arbitrary-precision evidence
  revision. Packet and local-state revisions also use `BigInteger`.
- Any login result and a role-list event reset only this evidence projection to
  defaults. Ignored events do not evict evidence or inspect nested state.
- Retain scalar fields only. No full item records, packet payloads, credentials,
  account identity, or catalog data are retained. S27-6's `s27_gold_field` remains
  a separately named observation; it is never an authoritative balance and
  cannot replace an S26 delta.
- Snapshots and their histories are deeply immutable. No service coordinator,
  `AccountSession`, lifecycle, scheduler, Android, UI, commands, or transport
  integration is included. A future owner must supply ordering/context explicitly.

`NpcShopOfflineOrder` is a caller-supplied historical description recorded when
one command was sent. It is **not** a capability token, proof that a command was
sent, or verification that the observations belong to it. There is currently no
live producer of this description. The caller must not invent one retrospectively
or interpret matching overlapping operations as settlement.

## Classification and invalid input boundaries

`ClassifyOffline` accepts typed evidence and an order. `ClassifyOfflineData` is a
narrow `StateValue` boundary for retained source-shaped evidence/order fields,
not a general Python serializer or external-data trust verifier. Both are pure,
offline, and return only `Status` and `Reason` with exact source text.

The source precedence is preserved: validate order fields, validate the event
list and 96-entry limit, test the first retained row for an expired window,
filter exact-integer packet counters after the start, detect mixed/duplicate
results, handle rejection/conflicting mutations, check reinitialization and
reliability, compare S26 delta, then compare bag evidence. An explicit rejection
can therefore precede a snapshot/limit uncertainty check, exactly as in Python.
Missing evidence stays pending, and a partial match expressly prohibits resending.

Descriptor integers reject booleans, floats, strings, nulls and out-of-range
values. Python's deliberately different observation equality is preserved: e.g.
a sale count of `True` equals one, while a purchase count must have exact integer
type and be positive. Numeric comparisons do not round large integers to doubles.
Unsorted, duplicate and invalid packet counters are not repaired. Buy quantities
sum without overflow. Buy ignores `bag_slot`; sell validates it in 0..255.

Source `ProtocolError` validations become `ProtocolException` with identical
messages. Malformed non-map evidence/rows fail with `InvalidOperationException`
(the equivalent boundary to Python's incidental `AttributeError`); required row
keys missing after filtering fail with `KeyNotFoundException`. These malformed
shapes are not normalized into empty evidence, pending, or consistent results.
The typed observer accepts the existing decoder models only; impossible raw
wire object shapes are not a second observation API. Typed snapshots constructed
externally with more than 96 rows are rejected by classification, while observing
a new relevant event trims to 96 as the source does.

## Verification

From the repository root, with the repository's Python dependencies available:

```sh
python dotnet/Lala.Core.Tests/World/Shop/generate_npc_shop_evidence_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~NpcShopEvidence
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
```

The deterministic source generator executes the retained Python implementation
and emits gzip **byte arrays** with the shared `TestSupport` helper, not large
.NET user strings. The unchanged gzip streams are held in separate partial fixture
files; generation rejects any output exceeding 500,000 UTF-8 bytes before writing. Hash verification normalizes only CRLF byte pairs, without
Unicode line splitting or other text transformations. Generation uses synthetic
observations and no commands, game connection, catalogs or private captures.

Coverage includes 50 full histories / 1,152 snapshot comparisons and 1,228 raw
classification cases: all receive orders, all ready/reliable combinations, all
nine relevant event types, ignored/reset events, 96/97/150 retention boundaries,
full immutable histories, arbitrary-precision counters, integral range edges,
malformed containers/fields, booleans versus exact integers, float/nonfinite
values, partial/split/duplicate/mixed evidence, rejection precedence, stale
windows, and seeded histories/corruptions. Contract tests also run decoded S26 and
S27 packets through the existing gold/bag reducers to demonstrate post-handler
context and the non-authoritative sale gold field.

These are offline parity and contract checks only. They do not establish runtime
integration, trusted order provenance, live server acceptance, actual payment
settlement, or physical-device acceptance.
