# Read-only expedition task assessment

`AccountRuntime.InspectExpeditionTask(taskId, selectedRoleIndices)` captures one
exact `PublicationSnapshot` under the existing runtime lock, then calculates outside
that lock. Pass an immutable array of one to four distinct nonzero role-slot indices.
The returned `ExpeditionTaskAssessment.Basis` is the captured historical token, not a
promise that the account, receive attempt or catalog is still current at return.
No independent caller-supplied catalog/state pair, callbacks or member search is used.

## Measurements

- Duration uses the received expedition level and same-catalog task/level definitions.
  Reduced minutes are rounded half-up before conversion to seconds, matching Python.
- RewardEmptySlots includes all ordinary and special rewards, even improbable ones.
  Kind 10 uses ceil(count/200) only for reviewed stackable items; kind 11 and other
  nonstackable item rewards use count. Repeated rewards are not pooled, existing
  stacks are not reused, and unknown kinds or item details leave the need unknown.
  Rules come from this catalog's reviewed ItemData, never server stack flags.
- ObservedFreeSlots counts absent keys within received capacity. Present zero-count
  entries still occupy slots. Ready/reliable bag and known positive capacity are required.
- ConditionMet and Success reuse the existing ExpeditionTeams formulas for exactly
  the selected roles. They do not establish role availability, unlocked teams, area
  availability, preference thresholds or dispatch feasibility. Observed role state
  is retained in RoleFaith. Negative received faith/stats are unsupported, not clamped.
- RoleFaith deficits target only this task's FaithCost, not an automation preference.
- RecoveryStock uses reviewed Special == 0 and the last attribute kind 64 minus 100,
  only when positive. Locked, timed or unavailable items are excluded; existing bag
  reservation/uncertain/exclusive/legacy-slot availability rules are reused. Current
  quantities, not original wire counts, are aggregated. No reservation is acquired.

Missing data is not zero. Typed Issues, nullable measurements, RecoveryStockComplete
and UnknownRecoveryItemIds distinguish absence or partial stock from a known empty
result. Invalid selection returns InvalidSelection; no owned Running publication
returns NoPublication. Missing/revoked catalogs return CatalogsUnavailable, retaining
any independently known free capacity. Missing task/level/outpost/role evidence has
specific issues. Partial known stock never proves whole-team restoration feasibility:
items are indivisible and the same stock cannot be promised to several members.

Imported bag guards cap hold groups, rows per group and each legacy slot list at 256;
negative counts/reservations on otherwise inspected eligible items, or excessive
structures or default imported slot arrays, yield incomplete InvalidBagData. Locked/timed entries are excluded first.
These defensive typed-input limits are not arbitrary-Python-input parity claims.
Results stay ResourceHeld and CanSendCommands=false. There is no CanDispatch/CanClaim,
packet, restore suggestion, timer, mutation, resource activation or new authority.
Hosts deliberately retaining results also retain the historical private source snapshot.
Default assessment diagnostics omit its contents; explicit fields are for deliberate use.

## Verification and boundaries

Fresh verification of this reimplementation used .NET SDK 10.0.403 on 2026-11-09:

- Regenerated 240 vectors by invoking the actual current Python manager helpers with
  deterministic synthetic data. Two independent generator invocations produced
  byte-identical output (SHA-256
  `0442ff980ae52d06ffb6c24287fc6270ddbc6b6409977e0fe59c1ec0c8cca5e1`).
- Focused Release suite: 261 passed, zero failed or skipped.
- Full Core Release suite: 43,734 passed, zero failed or skipped.
- External public consumer: build and run passed, zero warnings or errors.
- Independent read-only source review found no blocking issues.

These are fresh runs against the reimplementation, not reused earlier commit results.

Component tests use explicit synthetic ReviewedItemDetails. Runtime tests exercise
the real receive/resource join and retirement using an empty bag and the existing
private trust simulation; they do not prove reviewed faith-item stock through that
joined runtime. These tests do not verify official source admission, real account
behavior, Desktop integration or live-server acceptance. No UI, user computer or real
credentials are used.
