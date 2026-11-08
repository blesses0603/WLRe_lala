# Held account login and continuous receive

This internal integration connects `AccountSession` ownership, bounded TCP,
`ScriptedHandshake`, and `ReceiveAttempt`. It is not installed into Desktop or
Android and does not activate resource-dependent commands or a production profile.
All integration peers and credentials used by tests are synthetic and loopback-only.

## Ownership and ordering

- Account attachment precedes I/O and credential-provider invocation. Rejection
  leaves the session unchanged and releases the inert connection object.
- Verification uses its own bounded decoder. Like Python `verify_account`, the
  matching successful reply closes that separate leg immediately; unread bytes of
  that leg are not carried to the formal connection. This differs from the older
  test-only harness, which requires EOF and rejects trailing verification bytes.
- Formal login writes finish before its first bytes are delivered to the receiver.
  The same formal decoder and single-writer state coordinator process role selection,
  world initialization and all later traffic. There is no decoder reset, prefix copy,
  replay or handoff at world ACK completion.
- A serialized pre-commit hook processes handshake evidence and exact local write
  receipts before publication. It runs outside the receive lock, so retirement can
  cancel and close transport while a write or hook is pending. Late hooks cannot
  commit. Coalesced packets remain buffered and in order across awaited writes.
- Receive retirement synchronously revokes transport/provider/connect/write admission
  under the connection gate before asynchronous cancellation begins. Already-admitted
  writes may have reached the socket and are never replayed. A blocked provider
  finishing after retirement cannot start a login write.
- Only login, selected-role, two world ACKs, and heartbeat replies can be sent.
  After completion a repeated login result or role list fails the attempt. A local
  completed write is not proof that the peer accepted it. Failed, partial or uncertain
  writes terminate the connection; no retry or replay is generated.
- Clean transport EOF is drained before handshake failure is finalized. `Completed`
  in the receive result means framed source EOF, not successful authentication.
  `Login` is historical protocol evidence; current handshake/publication status must
  still be checked, and neither grants live/resource authority.

## Cancellation and reconnect boundaries

The login deadline covers both legs and the formal initialization, then is disabled
only after both world ACK writes complete. TCP read/write/connect limits remain in
force. `Begin`, `Disconnect`, explicit `Hold`, cancellation and disposal retire owned
work and wait for its cleanup through the existing receive owner. A noncooperative
caller provider/hook can keep completion pending; it cannot authorize a replacement.

Reconnect is explicit: finish old cleanup, begin a fresh generation and supply a
fresh transient login provider. There is no credential retention for retry, automatic
reconnect scheduler, saved-account store or host activation. The provider itself is
caller-owned and may close over sensitive inputs; it is cleared by this component
after initialization or cleanup. Encoded credential write buffers are cleared on all
exits. Raw TCP and game XOR do not provide credential encryption.

ResourceHeld remains unconditional, and public resource confirmation cannot clear
that generation's hold. This conservative later-Hold retirement is not Python
hold/resume parity. Runtime/resource admission, official server validation, Android
adapter wiring and native UI/device acceptance remain separate work.
