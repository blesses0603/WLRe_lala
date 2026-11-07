# Internal receive-attempt integration

`Sessions/Receive/ReceiveAttempt.cs` composes an already-created, read-only byte
transport with the actual wire decoder, server dispatcher and all 18 supported
`ServiceStateCoordinator` observer positions. It follows the receive ordering in
`wlre/network/client.py:485-517` and `wlre/core/state.py:154-174`.

This is an internal offline integration boundary, not a working game connection,
full Python State replacement, authenticated account session or resource loader.
No production transport implementation, socket dial, credentials, writes,
verification/login handshake, command dispatcher, runtime installation or Android
adapter is supplied. `AccountSession` and Android lifecycle APIs are unchanged.
The `authenticated` string in a received reducer snapshot is observation data,
not verified authentication or permission to activate anything.

## Contract

- The constructor has no I/O, threads or caller callbacks. The first `RunAsync`
  owns the only run and cancellation token. Subsequent calls share its fixed
  terminal result. Disposing a never-started attempt only cleans up its transport.
- A dedicated **Thread**, not merely a single async consumer, creates and owns
  one decoder/coordinator. Input continuations may run on unrelated threads.
- Each reader-owned byte array has a fixed size and crosses a bounded channel.
  Default capacity is four chunks of 4096 bytes, plus the reader/writer chunks
  and the decoder's uint16-length partial frame. Buffers are never reused while
  queued. The separate display channel retains at most one pending publication.
- Each packet gets inputs bound to the exact current immutable snapshot. The
  injected finite clock supplies `ObservedAt`; caller `ResourceHeld=false` is
  overridden to true. Parsed catalogs/metadata cannot release this gate.
- Decode, all observer reductions and the immutable commit are serialized with
  retirement. A failed packet has no published partial state or packet count.
  Prior commits survive a subsequent malformed frame in the same read. Framing
  currently feeds bytes individually to preserve this behavior with the actual
  decoder's batch-error contract. Throughput optimization is deferred.
- EOF calls `Finish`; cancellation never calls it on a partial frame. Missing
  Ark runtime evidence for a bound pending question has its own fixed failure
  code. The pump does not manufacture an `Absent` runtime read.
- Lifecycle (`Created`, `Running`, `Ending`, `Ended`) is separate from observed
  game phase. Publications contain attempt identity, successful-commit revision,
  status and immutable service snapshot. A saved publication must be checked
  against the owner's current attempt before reuse. Attempts never replay data.
- `Latest` includes lifecycle status. The optional callback observes successful
  commits, in order but coalesced, not a lossless packet log. Callback exceptions
  are isolated. A callback admitted before retirement may finish afterward;
  queued callbacks are dropped after retirement, and none outlive completion.
- Disposal retires identity synchronously. Cancellation callbacks and transport
  disposal run outside the state lock. Run and disposal completion wait for the
  actual reader, joined writer thread, observer, transport disposal and
  cancellation callbacks. A held read/callback/disposal keeps completion
  pending. Disposal failure yields `CleanupFailed`, `ResourcesReleased=false`,
  and a fixed `ReceiveCleanupException`; it never claims successful release.
  Repeated disposal shares one cleanup task, including its failure.

## Verification

Run from `dotnet`:

```sh
dotnet test Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~ReceiveAttemptTests
```

Synthetic `WireCodec` frames cover every byte split across login observation,
role list, world player, initial data, bag, storage, gold and attribute receipts.
Every intermediate and final service snapshot is compared with direct
coordinator composition, including immutable historical snapshots and pre/post
local evidence. Other tests cover byte reads completed on distinct actual
threads, fixed failure codes, malformed frames/XOR/payloads, all incomplete EOF
positions, provider/clock/Ark failures, bounded mailbox pressure, observer
coalescing/errors, cancellation/commit races, old-attempt replacement, late
noncooperative reads, repeated cleanup, held cleanup, cleanup exceptions and
cancellation callbacks during EOF cleanup.

This suite does not establish real-network throughput, authenticated readiness,
resource provenance, the ten runtime-table installation contract, automatic
operations, device acceptance or official-server compatibility. Source parity
and existing domain vector suites remain separate evidence. In particular,
Python resource hold continues receiving pending receipts; this pump does not
map that hold onto Android's terminal `ResourceHeld` lifecycle result.
