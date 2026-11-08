# Uninstalled bounded TCP transport

`BoundedTcpTransport` is an internal raw .NET Socket owner. It is not connected to login,
resource admission, the scripted handshake, AccountSession, or Android. Its only existing
integration is the read-only `IReceiveTransport` interface, exercised against loopback in
receive tests. That receive path remains `ResourceHeld=true`, regardless of observed packets.
There is no automatic login, command replay, reconnect, DNS, game endpoint configuration,
or active-session callback. **Game XOR is not encryption. Plain TCP does not secure credentials.**
Tests use synthetic byte buffers and ephemeral loopback listeners, never real accounts/hosts.

## Ownership and phases

Constructor snapshots numeric endpoint address bytes, IPv6 scope and port and allocates an
unconnected socket. `ConnectAsync` is one-shot; the first token owns it, and subsequent calls
return the same task. There is no changed-target overload. Phases are Created, Connecting,
Connected, Retired, Disposed. Connected is only TCP connectivity, never game authentication.
Invalid concurrent same-direction operations are rejected rather than queued. One read and
one write may run concurrently, with actual task completion checked before replacing a lane.

Any cancellation, timeout, EOF or I/O error retires the entire connection and closes the
socket. First terminal reason wins. No new operation is admitted after retirement. Disposal
is idempotent and waits for the actual connect/read/write tasks, not an earlier signal from a
finally block. Owned write bytes are zeroed before the write task completes. The caller owns
its input and read destination; no claim is made to erase copies outside this transport.

## Bounds and write meaning

Reads slice caller memory to at most 65,536 bytes. Writes reject empty/oversized input before
copying and own at most 65,539 bytes, the largest existing frame. Send syscall chunks are
bounded and only the unsent suffix is submitted after a successful partial syscall. This is
TCP byte completion, not application-command replay. Requested socket buffers are bounded;
the OS may adjust their actual sizes. Connect/read/write deadlines are positive and at most
five minutes, with smaller configurable values in adverse tests. There is no internal queue.

Complete means all bytes were locally submitted while the connection remained current.
It does not mean the peer read them, parsed them, accepted a command, or authenticated anyone.
NotStarted is returned only when no SendAsync was attempted. Once an attempt starts, any
failure/cancellation is PartialOrUncertain, even if ConfirmedLocalBytes is zero or the full
input length. ConfirmedLocalBytes counts only successful syscall returns and is not proof
of what reached the server. Do not automatically retry any uncertain write.

## Relationship to Python and verification

Python `wlre/network/client.py:101–103` uses sendall; `:120–142` isolates verification socket
ownership; `:425–438` connects and sends formal login; `:480–484` handles bounded reads/EOF;
`:536–544` publishes terminal cleanup. This migration isolates raw transport first and does
not claim the Python verification/formal protocol loop has been wired to it.

Tests exercise actual ephemeral loopback sockets: byte boundaries, fragmented reads,
immutable target, shared connect/dispose completion, pre-cancellation, bounded buffers,
full duplex, simultaneous pending operations, timeout and cancellation, peer half-close,
peer reset after a received-prefix barrier, caller mutation, and bounded backpressure.
On Linux only, a deliberately unaccepted, bounded loopback listen backlog tests connect
timeout/disposal. That test searches up to 64 loopback fillers rather than assuming an exact
queue capacity and does not run its backlog assertions on Windows/macOS. Those platforms
still run portable pre-cancellation/disposal tests; backlog behavior there remains unverified.
No assertions depend on exact elapsed milliseconds; deadlines prevent hung tests.
The existing receive attempt tests confirm EOF/truncation and continued resource hold.

## Validation (2026-11-07, Linux)

Release build succeeded with warnings treated as errors. Focused actual-loopback tests:
33 passed, 0 failed, 0 skipped. Impacted Sessions/Protocol suite: 2,917 passed, 0 failed,
0 skipped, including a second execution of the loopback tests. Each execution includes
20 barrier-released read/write/dispose admission races. The Linux backlog connect-timeout
and in-flight-connect disposal assertions ran; no Windows/macOS runtime result is claimed.
Independent review completed before compilation; its async assertion and completion-race
findings were corrected and re-reviewed. Final diff whitespace checks passed.

Compilation used the existing SDK/NuGet cache, writable XDG runtime/data/cache directories,
process-only 3 GiB GC cap and offline NuGetAudit=false. Dependency vulnerability auditing
and full integration regression are not claimed by this focused result. No real game host,
account, credential, resource-readiness transition, or Android activation was exercised.
