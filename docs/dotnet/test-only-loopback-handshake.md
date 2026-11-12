# Test-only two-leg handshake composition

This slice adds only `Lala.Core.Tests/Sessions/Loopback` test helpers and tests, not a Core
feature or production factory. The harness accepts only snapshotted loopback endpoints,
uses fixed fake credentials, and composes the existing BoundedTcpTransport, ScriptedHandshake,
FrameDecoder and ServerProtocol. No real game host/account, AccountSession, Android API,
activation callback or resource readiness is used. XOR is not encryption, and this test does
not establish secure credential transport. Original live/send flags remain false.

## Bytes, event order and lifetime

Each leg has exactly one serialized async reader/decoder owner. It reads at most 4 KiB,
feeds the real frame decoder one byte at a time, and processes each completed frame in order.
The unread suffix stays in that same owned buffer across awaited writes. Byte-wise feeding
prevents the bulk decoder from rejecting a later malformed header before returning earlier
valid packets in the same read. It completes each
real write, verifies connection ID/local byte count/outcome, and applies the exact scripted
receipt before consuming the next event, even if that event was decoded from the same read.
Dependent bytes arriving during writes stay in TCP. No competing reader, background event
queue or event callback can reorder them. Every accepted decoded event, including unrelated
initialization evidence, is retained in a bounded ordered test transcript.

Total inbound bytes are capped at 1 MiB, transcript at 4,096 events, and the overall deadline
at 30 seconds maximum. A read is at most 4 KiB; incomplete frame residual is at most 65,538
bytes, so the decoder's next feed is also bounded. Budgets span both legs and failure returns
only historical synthetic observations, never authority.

Verification and formal each use a distinct transport and decoder. Verification must reach
its terminal result and receive EOF with no complete or partial tail, then fully dispose
before formal connects. Formal must similarly reach both completed ACK writes, validate EOF
with no tail, and fully dispose before return. An extra event, partial frame, missing EOF,
uncertain write, cancellation or resource hold fails closed. These EOF requirements are
an intentional local-test protocol, not a claim that real game servers close at those points.

## Coverage and limits

Owned loopback servers exercise fragmented reads and coalesced writes, heartbeat responses
within batches, unlocked role selection, world/initial-complete ordering, unrelated gold data,
wrong-leg/kind evidence, complete/partial tails, early/truncated EOF, cancellation/hold on
either leg, and byte/event/deadline limits. TCP is free to split any server write; tests assert
correct ordering regardless of actual packetization, not a particular OS read chunk size.

Uncertain/mismatched receipt tests deliberately alter a result after a real local socket write.
They verify that composition rejects uncertain authority; they do not claim to deterministically
induce a partial six-byte send in the OS. The separate BoundedTcpTransport tests cover actual
loopback backpressure and reset uncertainty. All server tasks/sockets are owned by test helpers
and awaited during cleanup; normal success tests explicitly await server assertions.

No socket or decoder is handed to ReceiveAttempt. Actual game integration remains unfinished:
a single lossless owner must combine handshake and receive-state composition, or explicitly
transfer all decoder residual, decoded-but-unconsumed events and ownership without a gap.
Official source/runtime admission, credential handling and lifecycle activation remain separate
work. A successful local transcript does not solve or authorize those steps.

## Throughput limitation

Byte-wise Feed intentionally prioritizes ordering evidence over throughput in this bounded
local harness. The existing decoder allocates a result list per call, so feeding each byte
adds per-byte calls/allocations. No production throughput claim or performance optimization
is made. A future production decoder/owner should expose one-frame-at-a-time consumption
with an explicit consumed-byte count (or equivalent lossless cursor) while retaining earlier
valid frames when a later frame is invalid. Do not replace this test path with bulk Feed
unless that ordered-error contract is preserved and tested.

## Validation (2026-11-07, Linux)

Final Release focused tests: 29 passed, 0 failed, 0 skipped. Final impacted Sessions/Protocol:
2,946 passed, 0 failed, 0 skipped. Both runs include actual owned loopback sockets. Independent
static review identified and verified fixes for bulk-decoder ordered-error behavior, explicit
single-packet test constructors and cancellable peer barriers. Two additional final regressions
verify a nonterminal heartbeat is recorded and its real reply received before a later malformed
header, under read limits 1 and 4096. Those passed in both final runs; a further reviewer turn
for those test-only additions was unavailable, so they remain for integration diff review.

No production throughput, game interoperability, Windows/macOS runtime test result, credential
security, or active-state integration is claimed. Build used cached SDK/packages, writable XDG
paths, process-only 3 GiB GC cap and offline NuGetAudit=false; dependency vulnerability auditing
was not part of this verification. Final diff whitespace checks passed.
