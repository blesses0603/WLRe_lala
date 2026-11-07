# Offline scripted handshake boundary

`Lala.Core.Sessions.Handshake.ScriptedHandshake` is an internal deterministic coordinator.
It does not dial, read sockets, accept a resource readiness boolean, grant packet permission,
call Android `onActive`, install runtime data, or claim server interoperability. All receipts
are synthetic assertions. A completed transcript is explicitly `ScriptedComplete`, never
an authenticated production session. Existing AccountSession, ReceiveAttempt, reducers and
Android lifecycle APIs are unchanged.

## Source and deliberate differences

Python `wlre/network/client.py:120–142` verifies C63-7 kind 0 on a separate connection;
`:378–418` prepares formal kind 2 after verification and cancellation/resource checks.
`:269–281` handles heartbeat, formal success, roles and initial world ACKs.
`wlre/network/commands.py:30–41` requires an authenticated unlocked role selection.
`wlre/network/protocol.py:28–45,140–153` defines login/select and incoming event layouts.

Unlike Python's `player && initial_data_complete` world-ready condition, this coordinator
requires the correct completed login writes, corresponding phase/kind responses, a current
unique unlocked role, completed selection, both subsequent initialization observations,
and exact completed C12-1 then C3-2 writes. This is intentionally stronger offline ordering,
not exact Python behavioral parity. Early observations fail rather than being saved for later.
No role ID is invented from the role slot because S63-1 does not carry that mapping.

All inputs are serialized, and an outstanding write must be receipted before a new event.
This conservative offline contract is NOT a transport receive loop. A future transport must
preserve and serialize buffered events, support two separately owned connection legs and
independent decoders, and distinguish successful local writes from server confirmation.
EOF/timeouts/malformed frame or payload are mapped by that owner to `EndInput()`; this
coordinator accepts already-decoded events and has no timers or frame parser.

## Receipt, cancellation and memory ownership

Receipts must match attempt, leg, unique operation, complete byte count and SHA-256 digest.
Wrong/stale/partial/uncertain/replayed receipts retire the attempt without retry. Cancel,
hold and end-input revoke pending operations synchronously. No late receipt can revive them.
A hold never clears on matching resources or another observation. Start a fresh coordinator.

The coordinator stores no account/password or raw packet; its ephemeral pending digest is
private and cleared on completion/retirement. Login validation uses the caller's packet span;
encoding writes directly into one disposable buffer. The caller owns the input Packet and
must dispose the returned write after use. Disposal clears that owned wire buffer, not copies
made by the caller or credential strings used outside this class. Snapshots and write string
representations contain no credential data. This is not a secure credential storage API.

## Verification

`python tools/generate_dotnet_handshake_vectors.py` regenerates outbound bytes with the real
Python login/select/wire implementations, using only `synthetic_user` / `fake_password`.
Vectors cover verification/formal, both role slots, heartbeat and both ACKs. C# tests compare
both canonical wire encoding and coordinator ACK/heartbeat output to these vectors.
Adversarial tests cover phase/kind/role guards, undefined enum legs, null/default data,
receipt identity/content/outcome, replay, early observations, both initialization orders,
and cancellation/hold/end-input at every waiting phase and pending write.

Production resource admission is still absent. Offline candidates, matching version strings,
observation reducers and AccountSession's resource gate cannot authorize this transcript as
live. Official provenance, current package-pair identity, admitted runtime and transport
ownership remain separate prerequisites before any future Android adapter integration.

## Local validation result (2026-11-07)

- Release compilation succeeded with warnings treated as errors.
- Focused `ScriptedHandshakeTests`: 86 passed, 0 failed, 0 skipped.
- Impacted `Sessions|Protocol`: 2,884 passed, 0 failed, 0 skipped.
- Python vector regeneration was byte-identical (SHA-256
  `fc4ba3bae57689df8a1a457d277dc844fbb115fbd189dc57908652862fa3c384`).
- Independent static review found and verified fixes for undefined-leg and null-input
  guards, transient credential-copy reduction, and direct owned-wire parity coverage.
- `git diff --check` passed. No live credentials, game connections or Android activation
  were used. Full-suite regression is owned by the integrating branch, not claimed here.

Build used writable XDG runtime/data/cache paths and the existing SDK/NuGet package cache.
NuGet vulnerability auditing was disabled for the offline-cache restore; dependency security
scanning is not claimed by these tests. The process-only GC cap was 3 GiB.
