# Optional daily and weekly task catalogs

The resource pipeline now integrates `DailyTaskData_C` and `DailyTaskRewardData_C` as one
optional feature, following Python `daily_task_catalog.load_verified_catalog`. Both exact assets
must appear in the same freshly observed DataPackage manifest. Their declared bundle closures
are acquired and extracted with the existing native readers; neither table is guessed from
names or supplied through a public injection interface.

Skill and daily acquisition share one remaining download budget and one bounded set of owned,
verified bundles. Dependencies already owned by the required tables or an earlier optional
feature are reused. Reservations from a failed optional acquisition are not refunded. Missing
or corrupt cache content follows existing behavior; this feature adds no cache writes.

The existing version-agnostic daily parsers validate both payloads. The existing binder then
checks task groups, indices and progress slots, resolves names against this same candidate's
TextData, and checks task/chest item rewards against the same candidate's item IDs. Daily and
weekly definitions are retained; Shiny Pass is excluded exactly as in the existing binder.
Unknown goals remain unknown. These checks do not create gameplay or planner authority.

Only a successfully parsed and cross-bound pair enters the inventory input. A missing asset,
quota failure, ordinary acquisition failure or invalid cross-reference leaves the feature
unavailable while preserving the ten required tables. Cancellation, source drift and cleanup
failure still fail the attempt. All accepted rows share the existing database transaction;
immutable-row conflicts and uncertain writes still fail bootstrap, without a hidden retry.
Read-only refresh never adds missing daily rows: a previously ten-table inventory keeps daily
unavailable until an explicit bootstrap successfully persists the pair.

Independent readback opts into exactly these two additional table slots in the same transaction.
Both recorded and recomputed payload hashes must match the accepted preparation's exact raw
payload digests. A missing, malformed or mismatched member removes the whole daily feature from
the published candidate, without removing valid required catalogs or skills. The expected
digests are supplied internally from the owned preparation, never by a host. Provider, cleanup
and cancellation failures remain fatal. The existing 160 MiB readback payload budget is shared
across required, skill and daily slots; no extra arbitrary-table query is introduced.

`OfflineRuntimeCandidate.OptionalDailyCatalog` is a nullable `DailyTaskCatalogPreview`. It is
immutable point-in-time data: null means the optional feature is unavailable. `SourceSha256`
keeps its ten-required-table contract. There is no `DailyCatalogInput` activation token, automatic
planner execution, command permission, Desktop UI or connection-policy change.

## Validation scope

Synthetic UnityFS fixtures and temporary SQLite databases exercise the production composition
with valid task/reward definitions, same-version references and real readback. Offline test
sources remain non-authorizing even when their catalog is structurally complete. No official
network, real credentials or actual user database is used. Successful synthetic catalog
publication does not establish successful live resource acquisition or game-command readiness.

Focused Release verification passed 1,994/1,994 cases without skips, including bootstrap/facade,
required and optional acquisition, daily parser/binder cases, independent readback, and retained
Python readback parity. An initial run had 15 failures from two ImmutableArray assertions using
backing-array equality; ordered-content assertions corrected that test issue, and the full
selection then passed with no production change. Independent static review found no blocker.
The fixture generator validates against the original Python parsers/binder and reproduces all
21 fixture/evidence files byte-for-byte; earlier fixture bundles remain unchanged. Full combined-
head/platform verification is separate.
