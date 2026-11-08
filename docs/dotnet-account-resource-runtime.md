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
login, protocol compatibility or game-action authority. Optional reviewed SkillData, daily/weekly definitions and dungeon/co-op definitions can now be acquired and read back; remaining optional catalogs stay unavailable. See [optional skill resources](dotnet-optional-skill-resources.md).

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

For explicit local recovery after Committed/Unknown outcomes, see
[read-only inventory inspection](dotnet-resource-inventory-inspection.md). It checks fresh
persisted self-consistency without retrying preparation or granting resource admission.

Bootstrap also enforces an [active-inventory write precondition](dotnet-resource-inventory-concurrency.md)
to avoid overwriting another owner's changed active selector after source preparation. A conflict
is a failed preparation, not a queued or automatic retry; storage outcome still distinguishes
confirmed non-commit from cleanup uncertainty.

The integrated `AccountRuntime` projects available reviewed optional skill rows into
the current receive attempt's read-only `KnowledgeCatalog.SkillKeys`. Zero keys are
ignored; duplicate nonzero keys or inconsistent row IDs leave the mapping unknown.
Names, skill effects and command authority are not inferred. Reviewed item-fit values
are independently projected as described below. Revocation
removes the mapping on subsequent observations through the same exact-attempt catalog
join. Synthetic projection tests verify mapping only; no successful acquisition of
the actual pinned skill payload or live-account skill behavior has been validated.

Daily/weekly definitions are also integrated as one optional, cross-validated pair; see
[optional daily resources](dotnet-optional-daily-resources.md). They remain read-only and do
not activate planners or command permissions.

Dungeon/co-op definitions and declared normal-dungeon map IDs are covered by
[optional instance resources](dotnet-optional-instance-resources.md), with no room/entry permission.

## Reviewed equipment fit observations

`AccountRuntime` now joins `KnowledgeCatalog.ItemFitTypes` from the already prepared and
read-back `ItemData_C` rows, independently of optional skill availability. Only nonnull
`ReviewedDetails` supplies a fit value; those fields still require the existing fixed reviewed
ItemData fingerprint. Legacy/unreviewed rows remain unknown. Inconsistent item identities
make the item mapping unavailable without erasing independent valid skill mappings.

Fit values are retained exactly, including zero. The existing receive reducer alone applies
its source-compatible fit 11 to slot 7 rule; the projection does not invent or clamp slots.
This lets received equipment snapshots and damage/break observations use known item slots
while preserving unresolved/deferred behavior for unknown items. No extra database writes,
downloads, UI, automation, equipment commands or resource-hold changes are introduced.

The same exact-account/receive-attempt/resource-currentness checks govern every observation.
Revocation removes the mapping for new observations; already returned state remains historical.
Synthetic reviewed-row tests establish projection/receive mechanics, not successful acquisition
of the actual pinned ItemData bytes or live equipment acceptance.

Equipment-fit focused Release verification passed 1,238/1,238 cases with no skips, including
Sessions, combat knowledge and resource bootstrap/facade coverage. Eighteen new cases cover
independent maps, real held S23/S15 packets, late mapping plus deferred damage/break replay,
withdrawal, historical immutability and strict zero-outbound EOF. Initial fixture-only issues
(target-typed constructors in params calls and reopening a stream after half-close) were fixed;
production code and expected behavior were unchanged. Independent review found no blocker.
Full combined-head/platform verification remains separate.

### Reviewed companion skill slots

The required `NpcData_C` readback can additionally expose `ReviewedNpcs` (names and five ordered skill IDs) only under the existing reviewed NPC SHA-256. Other supported required-table versions remain usable, with this metadata unavailable. This reuses the required raw table and transaction; it adds no download, database table, or full combat catalog activation.

`AccountRuntime` passes the reviewed slot IDs into held companion observations independently of optional `SkillData_C` and Lua constants. Retained S15 slots can resolve when metadata arrives later; withdrawal removes metadata-derived skills on the next observation while keeping direct S8 evidence and raw slots. This supplies observed skill identity and level only, not skill definitions, combat readiness, or command permission. Synthetic parser/projection/framed receive tests do not establish live official-source acceptance.

Late NPC-slot reconciliation is an explicit integrated-runtime observation mode. The default standalone reducer preserves the Python stored-profile behavior (mapping only on S15); opting in refreshes metadata evidence on subsequent packets, including withdrawal. It does not change direct S8 precedence or the separate learned-skill consumer.

Verification: the focused Core regression run passed 8,204 cases, including existing Python parity fixtures, reviewed parser/candidate clone tests, direct and late S15 mapping, S8 overrides/removals, resource withdrawal, current-occupant identity, and strict zero-outbound loopback assertions. An initial change refreshed stored profiles by default; retained Python fixtures exposed that mismatch, so reconciliation is now explicitly opted into by `AccountRuntime` while the original default remains unchanged. Independent review found no blocker. Official NPC payload acceptance remains untested by these synthetic fixtures.
The subsequent full Core run passed 43,201 tests with no skips on the same compiled tree. Platform host builds and CI remain separate verification steps.
