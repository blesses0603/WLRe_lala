# Integrated account runtime

`AccountRuntime.Create` joins the public connection and resource runtimes for one
account generation. It is inert until `RunAsync`, which can send login credentials
to the explicit TCP profile, fetch official HTTPS resources, and write the fixed
SQLite resource inventory. Callers must authorize those effects before starting.
Neither successful login nor valid catalogs enable game commands.

## Lifetime and ordering

- Connection login runs first. No resource operation starts before the controller
  reaches `ReceivingHeld` for a current attempt.
- The first receiving attempt gets one bootstrap operation. Later receiving
  attempts use read-only refresh, never an automatic replay of the database write.
  This remains conservative even when the first bootstrap failed or was cancelled.
- Lifecycle changes use asynchronous identity-based signals rather than polling.
  Stop/reconnect revokes catalog selection immediately at the read boundary and
  requests cancellation of resource preparation. A pending, noncooperative resource
  callback must finish before another preparation starts or disposal completes.
- Current catalogs are joined only to the exact session snapshot and receive
  attempt. A successful historical preparation is not current authority.
- Failure/uncertainty in resource preparation leaves the connection held. It does
  not trigger a database rewrite or a login retry. Inspect/recover the inventory
  explicitly before choosing any later write.
- `Stop` revokes publications synchronously. Run completion joins connection and
  resource cleanup. Dispose before Run performs no login or resource acquisition.
  Aggregate cancellation/disposal uses this same stop boundary, so the underlying
  connection reason is `Stopped`; it does not claim a protocol failure.
- Receive retirement publishes `Draining` before transport cleanup completes, so
  resources are revoked even when that cleanup is slow or noncooperative.

## Receive observations

A current resource binding supplies decoded stage IDs and reviewed item stackability
rules to the actual receive observer. Missing aliases, skill maps and optional tables
stay unknown. Older receive snapshots can retain historical observations; they never
permit actions. Resource hold remains true at every receive commit.

`Snapshot` exposes bounded sanitized lifecycle/resource history. `Publication` is a
read-only point-in-time receive/catalog pair and becomes null after stop. Catalogs
and receive state must not be logged wholesale. The runtime exposes no command-send
operation and does not call `ConfirmResources`.

## Validation limits

Integration tests combine synthetic TCP peers, fixture bundles and actual temporary
SQLite writes/readback. White-box binding tests explicitly simulate only the private
owner trust bit and do not prove official provenance or live acceptance. The ordinary
fixture source continues to fail resource admission. No Desktop/Android host UI is
changed, and no official server or real credential is used by these tests.
