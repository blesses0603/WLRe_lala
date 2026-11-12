# Internal receive-attempt integration

`Sessions/Receive/ReceiveAttempt.cs` composes an already-created, read-only byte
transport with the actual wire decoder, server dispatcher and all 18 supported
`ServiceStateCoordinator` observer positions. It follows the receive ordering in
`wlre/network/client.py:485-517` and `wlre/core/state.py:154-174`.

This is an internal offline integration boundary, not a working game connection,
full Python State replacement, authenticated account session or resource loader.
No production transport implementation, socket dial, credentials, writes,
verification/login handshake, command dispatcher, runtime installation or Android
adapter is supplied by that original increment. The later internal AccountSession
attachment is described below; Android lifecycle APIs remain unchanged.
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

## Account generation attachment

`AccountReceiveTests` exercises the internal `AccountSession` receive-only attachment.
It accepts a caller-created transport only for a current `Preparing` generation and
immediately latches `Held`; login observations and matching version strings cannot
admit resources. The returned `ReceiveAttempt` owns transport cleanup, and the caller
must run and await/dispose it. Rejected attachment does not take transport ownership.

`Begin`, `Disconnect`, and explicit `Hold` synchronously revoke publication identity
and retire reception. A new generation cannot attach until the previous transport,
writer, and callback cleanup succeeds. Pending or failed cleanup blocks replacement.
Generation and attempt are checked together when pulling immutable publications.
Terminal snapshots can be read until retirement and are not proof of an active session.

One test uses actual loopback TCP with fragmented and repeated frames to demonstrate
continuous receive/reduction before EOF. Other tests control disposal deterministically
and cover stale identities, holds, duplicate admission, invalid construction, and failed
cleanup. No production endpoint, credential, UI, Android adapter, handshake handoff,
heartbeat writer, reconnection scheduler, or runtime activation is installed. In
particular this does not transfer the existing login harness's decoder/state; preserving
its unread suffix and state through login remains a separate integration increment.

Deliberate conservative difference: attachment starts in Held and continues receiving,
but a later explicit AccountSession.Hold retires its receive owner. This is not Python
resource-hold parity and is not intended as a live-session hold/resume implementation.

## Bounded runtime battle context

`ReceiveStateCoordinator` adds the battle-style/own-exit subset of
`SessionLogic.receive` plus bounded cooperative fight bookkeeping. It stages the complete
service reduction first, then restores a pending S11-10 announcement after the
S11-250 battle reset. The overlay and its private context commit together. The
next observation-input callback, the canonical coordinator and the published
snapshot share the same immutable result; nothing mutates after publication.
Standalone `BattleEventReducer` and `ServiceStateCoordinator` still clear style
on every start.

- Last announcement wins, including zero. Each start consumes it once; no
  announcement means unknown, regardless of prior style or unit layout style.
- The first own exit for `(battle count, current role)` clears a pending
  announcement and marks battle inactive, only when the count is positive.
  Role exits match the current non-null role (including zero); unit exits use
  the post-service exact slot's PID, never its master or NPC identity.
- Duplicate exits do not clear a later announcement. Winner, event end, role
  list and world-player packets do not reset this context. A new receive attempt
  starts empty, including when initialized from a historical service snapshot.
- On the first qualifying own exit with observed style 16, the overlay records
  the immutable `instance_combat.consume_coop_fight` bookkeeping after the full
  service reduction. `fight_consumed_battle` independently prevents a second
  decrement across role changes or a fresh private context on retained state.
  Positive integer counts decrement once; unknown, zero, negative and non-integer
  counts keep their original value and record null victory. Winner 1/2 and one
  distinct own-PID column 1..4 are required for victory, including exited units.
  PID zero can exit but cannot establish victory; Master never substitutes for PID.
  Authoritative count/room receipts retain their source-owned marker reset rules.
- Post-event status, deadlines, delay returns, pending event continuation,
  event-flow mutation, scheduler work and sends are **not** ported here.
  Resource hold and command authority remain unchanged.

`BattleReceiveGenerateVectors.py` executes actual Python `State.apply` followed
by `SessionLogic.receive`, with dormant services and a fixed clock. Its 13
retained synthetic sequences cover 112 snapshots, including historical snapshot
immutability and fresh context on retained state. `BattleReceiveContextTests`
also exercises stale-input/reduction rollback; `ReceiveBattleAttemptTests` covers
exact publication/input basis, invalid payloads, failed hooks and fresh attempts.
`AccountBattleReceiveTests` uses the public API and real local TCP sockets to
exercise style restrictions, unknowns, own/duplicate exits, next battles, and an
actual two-attempt reconnect with fresh synthetic credentials. It is not
official-server or real-account validation.

`CoopFightReceiveGenerateVectors.py` adds 41 actual Python `State.apply` then
`SessionLogic.receive` sequences with 302 snapshots, comparing every instance
field and the supported battle projection. Six explicitly recorded calls reach
Python's second consumption guard, then raise `TypeError` in the excluded
`time.monotonic() + None` delay calculation. The oracle checks the real state
left by those calls; it neither replaces receive nor treats that scheduling
failure as a Core requirement. Imported booleans/integral-float markers follow
Python equality while fight-count validation remains strict.

The cooperative coordinator tests also cover stale-input rejection and rollback
when an invalid imported instance map fails only after the service layer stages
an own-unit exit. Receive-attempt tests verify exact publication/input identity,
failed hooks/payloads, retained-state fresh context and historical immutability.
Public fragmented TCP tests cover full coop entry/room/count state, duplicate
exits, role changes, known/unknown victory, non-cooperative battles and reset of
consumed bookkeeping across a real new attempt. Peers permit only the existing
login/heartbeat exchanges; no post-battle continuation or command is sent.
