# Host-callable account resource runtime

`Lala.Core.Resources.AccountResourceRuntime.Create(session, absoluteDataRoot)` is the public
Core entry point for resource/database preparation. It owns the production resource owner:
fixed HTTPS source acquisition, ten-table extraction/decoding, the fixed SQLite inventory,
independent readback and source reobservation. Construction performs no network or filesystem
I/O. Public callers cannot supply a source, digest, manifest, provider or integrity assertion.

A host uses the same `AccountSession` as its connection runtime, creates one resource runtime,
and calls `BootstrapAsync(expectedAccountGeneration)` to create/update the inventory or
`RefreshAsync(expectedAccountGeneration)` for strictly read-only storage validation. Both
acquire current source bytes; refresh is not a disk-only/offline cache loader. The account must
already have a non-disconnected current generation. Wrong-generation/disconnected, busy and
disposed calls reject before work. The public facade is not installed into Desktop or Android.

The fixed path remains `official_sync/derived_catalogs/resource_inventory.sqlite3` beneath the
absolute root. Bootstrap writes resource tables, not credentials, an account database or game
state. Existing source bounds, schema validation, immutable collision checks and read-only
readback remain unchanged. Lexical containment is not protection against symlinks or hostile
filesystem replacement; no cross-process writer serialization is claimed.

## Lifetime and outcomes

Each accepted operation captures the exact initiating account snapshot, not just its numeric
generation. A same-generation Hold/phase transition or account replacement while preparation
runs prevents binding its late result. These account changes do not automatically cancel the
shared-resource write. The historical result preserves NotAttempted, NotCommitted, Committed
or Unknown storage even when a later step fails. No automatic retry, compensating deletion,
rollback claim or account-gate change is made.

One operation remains admitted through the entire resource-owner attempt and result selection.
Concurrent calls reject rather than queue or share caller cancellation. Invalidate synchronously
revokes selection and requests cancellation; a commit already admitted may remain durable.
Dispose revokes selection and joins owned I/O/callback cleanup. A preparation returning its
historical result can complete afterward, but cannot publish a binding after disposal.

The result exposes only status, account generation, storage outcome, readback-match and source
recheck booleans. Exceptions/URLs/paths/source contents are not returned. `WasBound` is historical,
not a capability. `HasCurrentResources` and `TryReadCatalogs` recheck both resource and account
lifetimes. Returned immutable catalogs are point-in-time data; later revocation does not erase
retained references, which must never authorize external effects.

Account snapshots change when reconnect starts a new generation, so the host must explicitly
prepare/rebind for that generation. Transport termination without a snapshot change is not
itself a resource revocation event. This is not a background source-version monitor. The
facade never calls Begin, Hold or ConfirmResources, never sends packets, and does not grant
login, protocol compatibility or game-action authority. Optional catalogs remain unavailable.

## Offline evidence

Internal test construction transfers ownership of an offline resource owner; it is unavailable
to public hosts and does not admit synthetic source evidence. Tests run synthetic bundles
through real temporary SQLite bootstrap/readback, missing-inventory refresh, account changes,
post-commit cancellation/invalidation/version drift, uncertain commits, confirmed cleanup
failure, overlapping calls and joined disposal. The public production factory is exercised only
for inert construction and pre-cancelled/rejected calls, without contacting official servers.
No real account, credential, user database or successful live TLS acquisition is exercised.

White-box facade-wiring tests modify the private owner trust bit by reflection in the test
assembly only to exercise Bound, public catalog reads and revocation after a synthetic pipeline.
They do not validate trust establishment or production acquisition. Separate unmodified offline
construction tests require the same synthetic source to remain NotAdmitted. There is no public
or production source/trust injection seam.

Status reports the original owner failure first: cancellation caused by Invalidate can report
Cancelled rather than Revoked. Both deny binding; the storage outcome is preserved independently.

Focused verification: owner/bootstrap/account-receive selection passed **111/111** Release
cases, with no failures or skips, using the unchanged full test project. The successful run
used a process-only 3 GiB GC heap cap, two reported processors, single-node MSBuild and disabled
shared compilation. Earlier test-assembly compilation attempts terminated or exhausted a
2 GiB compiler heap; they ran no assertions and are not counted as passing. Independent
read-only review found no blocker. Full combined-head/platform verification remains separate.
