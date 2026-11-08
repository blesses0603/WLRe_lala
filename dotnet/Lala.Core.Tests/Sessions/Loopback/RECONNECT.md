# Bounded held-account reconnect

`HeldAccountReconnect` is an opt-in internal owner over the existing two-leg
`HeldAccountConnection`. It is not installed into either platform and does not
clear the resource hold or add a command-sending API.

## Retry evidence

Each connection exposes a terminal outcome only for the exact result returned by
its completed RunAsync. Transport facts are monotonic: EOF or read failure cannot
overwrite a write failure/uncertainty, provider failure, deadline, or protocol error.
A historical world-ACK completion witness is distinct from current connection state.

Retries are limited to proven TCP connect failures (including connect timeout),
or completed-login remote EOF/read failure. Read timeout is conservatively terminal.
Incomplete login, rejection, malformed data, observation/reducer/pre-commit failures,
any failed/uncertain write, cancellation and cleanup failure never authorize retry.

## Ownership and cancellation

- Default maximum is three total attempts, with 1/2-second delays capped at 10 seconds;
  limits are explicit, validated and bounded. A five-minute recovery deadline covers
  credential acquisition, login and retry waits. It is disabled while a completed
  connection is receiving, then restarted for a later disconnect; a healthy session
  is not stopped merely because the recovery budget elapsed. Tests inject delay barriers;
  production defaults use cancellable Task.Delay.
- Every attempt requests a transient provider again. No login packet or write is
  cached for replay. The credential factory is caller-owned, may retain its own
  inputs, and is released by the controller on completion. A missing provider stops
  the run instead of reconnecting with stale inputs.
- Before retry, old transport, writer, hooks and provider operations must finish
  cleanup. AccountSession compares the exact previous generation and receive-attempt
  identity under its own lock, then creates a fresh Preparing generation.
- Explicit Hold removes receive ownership. Manual account replacement or Disconnect
  changes generation. Neither can be reversed by an already-scheduled retry.
- Stop, disposal, external cancellation and deadline revoke current connection write
  admission synchronously. Cancellation callbacks and physical socket cleanup remain
  asynchronous. Noncooperative factories/delay callbacks keep completion pending;
  they never permit an overlapping attempt or late credential use.
- One RunAsync owns cancellation and returns the same task on repeated calls.
  Dispose before Run is inert. Views, histories and outcomes contain only bounded
  status/identity evidence, not credentials or exception messages.

Tests use synthetic loopback peers and closed local endpoints. Coverage includes
fresh-generation reconnect after world initialization, bounded refusal retries and
backoff, repeated Run, hold/account replacement during delay, cancellation before
start, noncooperative acquisition/delay cleanup, missing credentials, deadline and
rejected login. Existing handshake/receive regression remains required.

Official source/runtime admission, credential storage or account selection UI,
Android adapter wiring, live server acceptance and native/device validation remain
separate. Safe read-only resource binding does not grant login or packet authority.

A future host must select a single reconnect owner. Do not nest this controller's
multi-attempt policy inside Android's existing retry scheduler; either delegate
retries to this owner or configure one attempt per outer lifecycle attempt.
