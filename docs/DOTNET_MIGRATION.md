# C#/.NET + Avalonia migration: parity and acceptance plan

## Scope and truthfulness

This is an incremental rewrite, not a completed replacement. The requested production boundaries are:

| Project | Responsibility |
| --- | --- |
| `Lala.Core` | Account/session state, packet codecs, battle rules, map logic, items/skills, expedition, social and task scheduling; shared resource/storage interfaces and implementations where platform-independent. |
| `Lala.Desktop` | Avalonia Windows/macOS presentation, desktop lifecycle and platform adapters. |
| `Lala.Android` | Avalonia mobile presentation plus Android permissions, service/notification ownership, overlay and lifecycle adapters. |

Core must not reference Avalonia, Android APIs, Tk, Kivy or a Python interpreter. UI sends explicit commands and consumes immutable state snapshots/events. It must not decode large resources, block on network/storage, or construct unrelated hidden pages on its UI thread. The requested three projects are production boundaries; automated tests are separate test projects, not another runtime architecture.

The Python application remains available until replacement features are accepted. Do not delete original code, credential stores or resource databases merely because a C# type exists. Do not enable live commands because a demo, compilation or codec test succeeds. No official-server actions or spending are authorized by this inventory.

## Confirmed shared-core responsibility map

Keep one `Lala.Core` project. The following are responsibility boundaries, not a claim that every module is already implemented or a requirement to rename working code immediately:

- Accounts / Sessions: account isolation, session generations and event-driven login/role state.
- Transport / Protocol: connection adapters, bounded framing, exact packet layouts and dispatch. Decoding never itself authorizes an action.
- State: single-writer ownership, service mutation scopes, reducers and immutable published snapshots.
- Resources / Catalogs / Storage: official-source identity, reviewed parsing, generation/cache activation and atomic persistence.
- Battle: rules, evidence, efficiency and eventual battle orchestration.
- World: maps, navigation, position reconciliation and runtime obstacles. Preview routes are not movement permission.
- Inventory / Skills: owned items, reservations, skill data/rules and operations; bag and skills may load independently.
- Expedition: team conditions, results, state and scheduling.
- Instances: dungeon instances and verified dungeon sweep behavior.
- Social / Organization / Ark: chat, groups/guilds and ark-specific state/services.
- Hero challenge: a separate feature boundary for entry, element and difficulty; do not treat dungeon sweeping as hero challenge or invent unverified protocol behavior.
- Automation / Scheduling: deterministic service coordination, deadlines, cancellation and safe pending-request settlement.
- Safety / Diagnostics / Abstractions: resource holds, command guards, redacted evidence and platform-neutral contracts.

Migration remains source-driven and incremental. Existing verified files are moved only when integrations and tests justify it. Android/desktop hosts stay outside Core.

## Source baselines

- Desktop: `blesses0603/WLRe_lala`, main `0f8bf6a99a70070cea1aeec60a0d6ca93dbc581a`.
- Android: `blesses0603/WLRe_lala_Android`, `348163c32d3b20a2d0d380a639691b7b072c0e09`. A fresh `git ls-remote origin refs/heads/main` on 2026-11-07 returned the same SHA: no baseline difference at that check. Recheck before final migration acceptance because remote changes may continue.
- Open Python work such as PR #77 is not automatically included in this main baseline. Reconcile approved later fixes and UI behavior before final parity acceptance; do not overwrite unrelated branches.

`dotnet/migration-inventory.json` indexes partitioned JSON module files recording every tracked Python file outside tests in both checkouts: **696 entries** (416 desktop, 280 Android). This includes **536 runtime modules**, 139 developer tools and 21 Python-for-Android build recipe files. Package `__init__.py` files are included for source completeness, not treated as standalone user features. Desktop `wlre` has 320 modules; Android has 167 `wlre` modules and 47 `android_app` modules. Each entry records its source hash, target project/subsystem, top-level source definitions, imports, candidate existing tests and acceptance profile.

Inventory entries began `not_migrated`; only the evidenced first-increment subsets below have been updated. Implementation authors must update `target_files`, status and verification evidence as individual slices pass. A referenced test is a **candidate**, not proof of coverage. Do not silently change all statuses to complete after a solution build. `offline_parity_verified`, `platform_verified` and `live_verified` are distinct gates; truly obsolete build recipes may be `retired_with_reason` only with the replacement and verification documented.

Android's `MIGRATION.md` explicitly says its `wlre` core is a local copy requiring manual synchronization. The inventory compares corresponding source hashes. Different hashes require behavioral reconciliation, not independent translation into two C# cores. Duplicate copies are not additive estimates of unique rewrite effort.

## Executable first-increment draft (not the full migration)

The first C# increment is an executable offline foundation, not a replacement LaLa client. The Python implementations and their unported features remain necessary.

| Source / new capability | Current scope | Not established |
| --- | --- | --- |
| `wlre/network/wire.py` → `Lala.Core/Protocol/Wire.cs` | `ported_offline`: packet primitives, strict strings, framing/XOR and incremental decoding have Python golden-vector parity. | Parser diagnostics `read_checkpoint` integration is still outstanding; no formal-server acceptance. |
| `wlre/network/protocol.py` → `CandidateCommands.cs` | `partially_migrated`: login/select-role/walk/attack/skill/item **byte builders** only; synthetic Python-generated vectors. | Live login/transport, full command dispatch and server acceptance are not implemented by these builders. Separately evidenced receive decoders and scripted handshake guards do not grant authentication. A builder is not permission or readiness to send. |
| `wlre/network/resource_safety.py` → `ResourceSafetyPolicy.cs` | `partially_migrated`: `AllowsDuringHold` policy only. | Remaining routing and full resource/version lifecycle integration. |
| `wlre/services/battle/combat.py` → `CombatRules.cs` / `BattleDisplayRules.cs` | `partially_migrated`: `normal_skill`, `effect_text` and the later pure `unit_label` / `attack_lines` slice; 576 focused tests include 450 earlier rules tests and 126 display tests. | Live catalog loading/activation, observer/UI wiring, complete auto-battle and live acceptance remain. |
| New `AccountSession` | Offline session generations, version-match confirmation and latched holds with subset tests. | Complete authentication, credential persistence, socket ownership, reconnection or parity with the original session lifecycle. |

Evidence lives in `dotnet/Lala.Core.Tests/Protocol/WireTests.cs`, `PythonGoldenVectors.cs` `dotnet/Lala.Core.Tests/Sessions/SessionTests.cs`, and `dotnet/Lala.Core.Tests/Battle/CombatRulesTests.cs` / `PythonCombatVectors.cs`. Test/build results apply only to their listed scopes. The inventory's `ported_offline` status never means `live_verified`; Android duplicate copies remain unreconciled until their behavior is explicitly compared. UI/platform scaffolding is not Android service, notification, lifecycle or device acceptance.

## Functional parity map

| Area | Python evidence | Required C# acceptance |
| --- | --- | --- |
| Framing / codecs | `wlre/network/wire.py`, `protocol.py`, `layouts.py`, `live_data.py` | Byte-identical fixture output, incremental/concatenated input, bounds, overflow, malformed strings and incomplete final frames. Preserve the source's candidate/unverified outbound-codec warning. |
| Account session / transport | `wlre/network/client.py`, `connection_health.py`, `command_envelope.py`, `resource_safety.py`; Android `sessions.py`, `runtime.py` | One owner per connection, bounded queues/timeouts, cancellation, stale generation rejection, account isolation and no duplicate command after reconnect. Replay before live login. |
| State / events | `wlre/core/`, `wlre/network/state_updates.py` | Snapshot and event parity, atomic updates, repeated/out-of-order/old-session events, unknown result is not success. |
| Battle / companions | `wlre/services/battle/`, `wlre/core/state_battle_events.py` | Target/range/resource checks, current state before command, round limits, victory/defeat/disconnect handling and server-confirmed results. |
| World / navigation | `wlre/services/world/`, `wlre/features/minimap`, `portals`, `npc` | Same-version verified map data, coordinate/layer/path constraints, corrections stop movement, unsupported geometry stays blocked. A preview is not movement acceptance. |
| Items / skills / storage | `wlre/services/items/`, `wlre/storage/`, `wlre/ui/bag.py` and skill UI where present | Read parity, icon provenance, quantities, costs, latest-state validation, no duplicate consumption and safe schema migration. Standalone skills should not construct inventory/warehouse pages. |
| Expedition | `wlre/services/expedition/`, `wlre/network/expedition.py` | Selection/eligibility/limits, confirmed dispatch and claim, cancellation and interrupted/repeated replies. |
| Social / organization | `wlre/services/social/`, `wlre/network/social_protocol.py` | Correct recipients and display; sends only explicit actions; contribution budgets and server-confirmed progress preserved. |
| Daily / scheduled automation | `daily_assistant.py`, `daily_tasks.py`, `star_ark.py`, `time_cube.py`, `service_scheduler.py` | Server day semantics, bounded budgets, one outstanding command, unknown-result stop, stale completion guards, cancellation and reconnect. |
| Resource versions / parsers | `wlre/services/world/`, `official_lua_index.py`, `parser_diagnostics.py`, `wlre/storage/normalized_resources.py` | Same manifest/version identity, schema and hash checks, no stale fallback, deterministic diagnostics and failed-download retry. |
| Desktop UX | `wlre/ui/`, `WLRE_Client.py` | Windows and macOS native run; interrupted login, repeated open/close, late async completion, resize, CJK text and high-DPI; measured cold/warm opening without UI blocking. |
| Android UX / host | `android_app/`, Java sources below | Same shared Core with platform host; emulator and device lifecycle/security acceptance, not desktop-only proof. |

All production modules are individually mapped in the JSON inventory; the table is a grouping, not a substitute for the source-level checklist. Unverified hero-challenge (挑戰英傑) or dungeon protocol work is not mature existing functionality. Dungeon sweeping and the hero challenge remain separate features.

## Android platform contract (not solved by Avalonia UI)

### PR79 Android lifecycle increment

The Android C# host now has a single selected-account coordinator, a process-wide runtime owned by the foreground service, local Binder observation, notification/permission flows and network monitoring. The platform-free contracts are under `Lala.Android/Lifecycle`; Core APIs are unchanged. The default Core adapter is explicitly unavailable and never opens a socket or reports a synthetic active session. This is partial host migration, not parity with the Python multi-account service, credential vault, integrity checks or live transport. See [Android lifecycle responsibilities and acceptance](../dotnet/Lala.Android/README.md).

The historical Python `dataSync` declaration below is reference evidence; the new host chooses `specialUse` with a declared subtype for a user-started ongoing game connection. Play review and device acceptance are not established by that choice. Notification denial defers startup by product policy. Activity backgrounding does not own cancellation of a started session; explicit stop, platform stop and process death do. No persisted login or boot restart is added.

Evidence is from the Android baseline above, not a promise that the old implementation satisfies every newer OS rule.

| Contract | Source | Required migration and tests |
| --- | --- | --- |
| Permissions / service declaration | `buildozer.spec:17-26` | Current source requests INTERNET, WAKE_LOCK, FOREGROUND_SERVICE, FOREGROUND_SERVICE_DATA_SYNC, POST_NOTIFICATIONS and SYSTEM_ALERT_WINDOW; dataSync foreground service; API 35 target, API 31 minimum, arm64. Review current .NET/Android requirements before selecting new target/minimum. Do not blindly copy or automatically grant permissions. |
| Background connection owner | `android_app/service.py`, `runtime.py`, `sessions.py` | Service owns sessions independent of visible activity; preserve account isolation, bounded RPC/queues and clean stop. Decide explicitly whether in-process service or IPC replaces the Python Unix socket host. Two hosts must never issue commands for one account. |
| Notification / stop action | `java/org/lala/client/ConnectionService.java` | Low-importance channel, private visibility, immutable PendingIntent, reopen activity and explicit stop-all action. Test denial on Android 13+, repeated starts, stop and process recreation. No credential or sensitive account details in notifications. |
| Android 15 service timeout | `ConnectionService.java:onTimeout` | Stop safely and destroy overlay; no automatic reconnect loop to defeat OS limits. Verify device/target-version behavior. |
| Wake lock | `service.py:metrics` | Bounded 300000ms lease while sessions active, renewal after 240s in source, release when idle/finally. Reassess necessity; verify no leaked lock. |
| Overlay | `java/org/lala/client/FloatingOverlay.java`, `overlay_state.py`, `app.py:toggle_overlay` | Optional, user-approved draw-over-other-apps permission; denied permission must not terminate game sessions; cleanup at stop/timeout; touch and orientation tests. |
| Account vault | `vault.py`, `credentials.py` | Android Keystore AES-256-GCM; key never exported, no-backup private directory, safe atomic ciphertext writes. Preserve old encrypted records on failure. Migration across package/signature/key-alias changes requires an explicit compatibility plan; do not fall back to plaintext. |
| Installed-app integrity | `integrity.py`, `java/org/lala/client/RuntimeIntegrity.java` | Activity and service independently verify package/signer before vault/network use. Pin only authorized signing identity; no unrequested key rotation. Wrong signer and service-only start must fail safely. |
| Pause/resume | `app.py:682-786` | Clear password on pause/stop; background host continues only as designed; foreground restoration uses existing session snapshots without re-login; test long pause, recreation, low memory and rapid navigation. |
| Transport trust | `tls.py`, `resource_sync.py` | Preserve verified TLS/certificate behavior and resource version gates; no accept-all certificate callback. |

Java sources are non-Python migration obligations and therefore documented separately from the Python count. Fonts, official icons, manifests, database schemas and build signing configuration likewise need asset/licensing/integrity review; source-code inventory alone cannot establish full application parity.

## Dependency decisions / risks

1. **UnityPy 1.25.4 / UnityFS**: desktop `requirements-extractor.txt` and `wlre/services/world/unity_textasset.py`, `navigation_sync.py`, `auto_catalog.py`, `portrait_assets.py`, `item_image_database.py`, `emoji_database.py`. A bounded internal C# UnityFS/TextAsset subset now has genuine owned-writer fixture, independent-decoder and one real-bundle extraction receipt, with no runtime decoder package dependency. Wider actual-game extraction, unsupported layouts, image/other asset types, production runtime pipeline wiring and Android/AOT remain unverified or unimplemented. The precise format, allocation limits and single-sample boundary are documented below; this is not a complete UnityPy replacement or a generic JSON substitute.
2. **Official Lua data**: `wlre/services/world/official_lua_codec.py` uses PyCryptodome AES-CBC and strict padding/round-trip verification; `official_lua_index.py` verifies path/hash inventories. Port only the reviewed data codec using .NET cryptography and deterministic tests. Never execute downloaded Lua as part of data loading. Do not publish or log secret key material in fixtures.
3. **SQLite**: preserve schemas, version identity, transactions, read-only provenance and atomic rebuild behavior. Select a maintained .NET binding and validate native packaging on Windows, macOS arm64/x64 and Android arm64. Database load success does not establish schema compatibility.
4. **Pillow/Tk/Kivy/PyJNIUS**: replace with Avalonia rendering and native .NET Android adapters, not a Python runtime hidden behind the interface. Decode/verify off the UI thread and marshal only UI-safe results. Preserve CJK font and image source metadata.
5. **Nuitka / Buildozer / p4a recipes**: not C# compilers. Replace with .NET/Avalonia and Android build jobs; document removed recipes and native codec equivalents. No release or signing changes implied by a draft PR.
6. **Mixed-language transition**: a temporary Python extraction tool may be useful only if explicitly documented and approved as a transition. It cannot be described as an all-C# replacement. Core offline tests must run without Python when their fixture inputs have been generated and checked in.

## Delivery gates

1. Freeze/reconcile source baselines and test fixtures; list verified, partial and unverified original behavior.
2. Build Core on its own; validate a real codec/resource/state vertical slice with deterministic differential tests. No live connections in demo/replay commands.
3. Build and launch desktop Avalonia UI displaying real parsed offline data; clearly label fixtures. Measure responsiveness with cold and warm loads.
4. Port sessions and operation guards, then one complete functional flow at a time. Preserve original Python reference and contract tests until parity is demonstrated.
5. Port remaining subsystems from the inventory. A feature's UI, data path, error/cancel behavior and server acknowledgement are part of the same acceptance unit.
6. Build Android APK from the same Core; emulator and real-device foreground/background, permission, service, overlay, network and secure-storage tests.
7. Native Windows/macOS builds and installations, Android installation/signing continuity, configuration migration/rollback, then explicitly authorized formal-server acceptance. Do not retire Python before these pass.

A draft PR may publish a useful tested increment while gates remain open. Its description must enumerate implemented slices and unresolved items and must not say “all code migrated” until the inventory and platform gates support that claim.

## Additional verified offline increments

| Source / capability | Current scope | Not established |
| --- | --- | --- |
| `wlre/network/command_envelope.py` → `CommandEnvelope.cs` | Offline port, Python validation/name parity. | Not yet integrated into live dispatch. |
| `wlre/network/connection_health.py` → `ConnectionHealth.cs` | Partial offline transport evidence port with injected clocks. | Socket keepalive and exception metadata remain; quiet is not logout. |
| `wlre/services/expedition/teams.py` → `ExpeditionTeams.cs` | Partial offline conditions/rates/team selection, 408 parity and boundary checks. | No protocol, scheduler, UI or live expedition integration. |

Historical first-increment run: **952 passed**. Newer scope-specific evidence follows; test counts include synthetic parity and boundary cases, not end-to-end game features.

The inventory index uses schema version 2: load the relative `module_files` to obtain all 696 entries. Partitioning keeps individual review/upload units small; no source entries were removed.

## Core state and task integration increment

The current batch adds immutable battle/world reducers, pure time-cube and
daily-task lifecycle planners, and receive-only storage/recovery/crafting
layouts. The common dispatcher preserves full inventory records; schedule
layouts require explicit context and remain unsupported without it. Candidate
packets are not sends or spending authority. No AccountSession, transport
lifecycle, UI or Android implementation is expanded by this batch.

Automation source parity covers 233 packet vectors and 74 sequences / 669
transitions; battle covers 20 sequences / 602 checkpoints; world covers 68
sequences / 934 checkpoints plus 288 scope cases. Inventory includes 418 source
vectors, malformed prefixes and maximum-count boundaries. Fixtures are synthetic
and offline; these counts do not establish complete feature or live parity.

The owner-thread `LocalStateCoordinator` now combines session/world/battle
observations, shared phase/count and current player identity, with immutable
snapshot publication. Python routing/helper parity covers 283 checkpoints and
coalesced publication covers 23 operations. Later increments below compose the
service observers and an internal receive-only byte source; authenticated account
lifecycle and production network routing remain unintegrated.

Ark and tent receive decoders now join the common dispatcher. They preserve
strict Ark flags and permissive source-defined tent fields, ignored nonempty
acknowledgements, empty snapshots and S65-13 geometry fallback. Synthetic Python
parity covers 2,261 cases and 16,598 prefix outcomes; service reducers/planners,
commands and live activation are still outstanding.

Daily-task task/reward table parsing and metadata binding are available as an
immutable offline preview. Missing groups, duplicate slots, names, item references
and condition goals follow the retained Python contracts. Projection into planner
definitions does not supply a verified identity or create `DailyCatalogInput`;
resource extraction, verified activation and live execution remain outstanding.

## Receive-state increment

- Storage/recovery: immutable counts, first garage identity, insertion-ordered
  reservation deductions, unknown potion baselines and latched reliability.
  Receipt-only events do not infer resource credit, debit or completed transfers.
  Python parity: 147 sequences / 3,634 snapshots and count queries.
- Guild: receive roster/profile/membership/self-leave/disband state. Python retains
  stale rosters across role changes; readiness must not authorize actions. Member
  presentation order remains outside this snapshot contract. Python parity:
  26 sequences / 2,183 snapshots.
- Expedition: defaults, receive application and injected-clock deadlines preserve
  signed attributes, ordinal slots, revision changes and pending rejection
  uncertainty. Start acknowledgements and result clearing do not confirm a claim.
  Python parity: 63 sequences / 4,537 steps.

These are immutable domain reducers, not complete service observers or a live
session adapter. Transfers, recovery execution, expedition automation/confirmation,
guild actions, account lifecycle and formal-server acceptance remain outstanding.

## Offline service composition and live-data receive slices

`ServiceStateCoordinator` composes daily tasks, time cube, recovery, guild,
activities, storage and expedition before local world/battle/session dispatch in
source order. Inputs bind to the exact current snapshot, resource holds default
on, and published state is immutable. Typed reduction failure rolls back the
entire observation/count, intentionally stronger than Python's partial mutation.
Fourteen real Python State.apply sequences cover 698 checkpoints and 36 event
kinds. Later increments below compose the remaining observer positions; this is
still not complete State parity.

Separate bag/companion receive reducers preserve slot metadata/order, inventory
reliability, identity-sensitive reservation observations, unknown baselines,
companion append/reuse and buffered S8 attributes. Seventy-seven Python sequences
cover 1,616 snapshots. Later receive increments below add player/battle knowledge
and equipment/deferred updates; separate pure helper/candidate slices are also documented below. Live
resource use and full shared-session wiring remain outstanding. These receive
functions neither acquire reservations nor perform resource-consuming acts.

Crafting/furniture receive snapshots now preserve queue and furniture insertion
order, ownership, readiness, sparse tool rows, compaction, error receipts and
pending uncertainty. Elapsed-time queries use an explicit timestamp and never
claim completion. Python parity covers 140 sequences / 5,225 snapshots. This
slice is now composed into ServiceStateCoordinator but does not implement recipe/tool
planning, material confirmations, output tracking, timeouts or automatic execution.

The mixed service coordinator now includes crafting and the bounded bag/companion
apply_live slices, in source order. Shared stackability and companion attributes
remain consistent across projections, with distinct before-observers, before-live
and after-live bag evidence. Thirteen additional State.apply scenarios cover 524
checkpoints. Later increments add player/battle knowledge and all remaining observer
positions and an internal receive-only pump; production transport and complete
State remain outstanding.

Party and tent receive snapshots are also available independently. Party preserves
ordered team merges, current-role queries and explicit request expiry without
inventing readiness or stale-event rejection. Tent receives use post-world role
and scene, separating visibility from deployment and preserving uncertain pending
evidence. Neither performs commands or runs timers. They now join the common coordinator;
full lifecycle/command integration remains outstanding.

Dungeon/cooperative receive state now includes the six existing creation/room-flow/
standby/start/entry/reward observers. Typed observations preserve uncertain pending
work and distinguish acknowledgements, room evidence, scene entry and incomplete
reward receipts. Role identity must be supplied before local world dispatch; catalog
map IDs are caller declarations, not verified provenance. Python parity covers
1,173 sequences / 5,527 steps. Commands, timers/disconnect, session wiring and live
acceptance remain outstanding. No generation, dungeon sweep or hero challenge is
invented where the retained source has none.

Large Automation/Ark/Tent decoder fixtures now use deterministic gzip byte arrays.
All original JSON payload bytes and cases are retained; compiled-payload hashes and
regeneration match. This frees about 3.46 MiB in the C# user-string heap and reduces
the test assembly without changing production logic or skipping verification.

Party and instance observers are now composed before local dispatch; tent follows
it. Explicit instance map declarations default empty and do not establish catalog
provenance. Twenty-two mixed State.apply scenarios cover 679 checkpoints and 50
event kinds. Attribute allocation also has an independent receive reducer, requiring
post-apply_live player stats and a server acknowledgement; it now joins the shared
receive workflow, while actual allocation commands remain outstanding.

The remaining player/companion/battle knowledge receive slice now preserves current
gear separately from original received layouts, bounded deferred equipment evidence,
player stats/skills, and exact identity matching. Forty Python sequences cover
1,646 checkpoints. Its replacement projections are now wired before allocation and local dispatch.
Twenty-six mixed State.apply scenarios verify 1,064 checkpoints, including same-packet
allocation completion and current gear retained independently of historical layouts.

Guild-action receive state now ports defaults, apply_actions and reset_day with
explicit already-reduced guild plus post-local player/gold context. Forty-six Python
sequences cover 2,370 historical snapshots. Pending evidence never authorizes a
request. Receive observations now join the shared coordinator. The scheduler-position
non-sending tick prefix, planning and spending remain unported; no scheduler call is
inferred from receive.

NPC shop evidence now has a bounded immutable 96-event observation history and
offline classifier, with 50 Python histories / 1,152 snapshots and 1,228 classifications.
It preserves uncertain outcomes and never treats the S27 gold field as an authoritative
balance. Observations now join the post-local flow, while a genuine historical order
descriptor producer remains a separate gate; correlation is not payment settlement
or permission.

Efficiency now supports detached immutable staging and a typed receive adapter with
explicit timing. Original tracker calculations remain unchanged. Knowledge projection now requires current player/companion evidence and post-local
identity explicitly. Self and companion slot zero are distinct, UInt16 companion
subjects are preserved, and Int64 level/degree values are validated before curve
lookup rather than narrowed. Eleven Python receive sequences cover 166 checkpoints.
The shared observer is now integrated; runtime/device acceptance remains outstanding.
No test-policy change was made for local resource-pressure retries.

Ark defaults and receive transitions now expose immutable state plus identity-bound
Observe/Confirm/Reject memory intents. The 371 retained-Python sequences cover 3,494
snapshots and 48 helper-boundary intents using the actual caught storage-failure path.
Default deferred composition is separately tested and does not claim storage failed.
No receive intent is persisted or accepted as a correct answer. A separate explicit
offline store, strict arithmetic solver and reviewed candidate resolver are available
below; runtime persistence, resolver/solver-to-runtime completion and execution remain
gaps. The post-local coordinator requires explicit runtime reads when source branches
consume them; missing input is not mislabeled as an observed
unavailable runtime.

`ArkQuestionStore` now implements an explicit offline SQLite evidence boundary using
a caller-supplied factory for a new closed `DbConnection` per operation. It recomputes
the full catalog/role/question identity and supports observation, reviewed candidates,
durable once-only claims, attempts, caller-supplied confirmation, rejection and permanent
conflict quarantine. Transactions reserve the writer before schema/evidence reads and
commit only after the complete operation. Compatible Python v0/v1/v2 databases migrate
to v2; unknown/corrupt schemas or contradictory persisted evidence reject without reset.
This stricter validation is an intentional difference from permissive Python reads.

The source oracle supplies 104 identity vectors, 149 scenarios / 1,402 operations and
three Python-created database images. Rollback, cancellation, bounded lock contention,
competing writers and retained quarantine have contract tests. Microsoft SQLite packages
are test-only; Core does not select or initialize a provider, choose paths, execute receive
intents or validate a live session/generation. Hosts must schedule synchronous I/O off
the UI thread. Cancellation is cooperative; the test provider's one-second command
timeout differs from Python's 250-ms connection timeout. Uncertain commit failures do
not synthesize success or trigger automatic retries. `Confirm` records explicit caller
evidence without authenticating a server receipt. Production provider/native packaging,
private paths and lifecycle, reviewed-candidate/solver-to-runtime integration,
command sending and runtime/device acceptance remain open. See
[Ark storage boundaries and evidence](../dotnet/Lala.Core.Tests/Storage/README.md).

`ArkArithmeticSolver.Solve` separately ports only the strict arithmetic in
`wlre/services/ark_first_answer.py`. The whole question must match the retained grammar;
bounded integer/rational evaluation never rounds, and exactly one option label must
match numerically. Python-compatible label stripping includes all 29 whitespace
characters. Unsupported, fractional, zero-divisor and ambiguous results return null.
The 304 actual-Python cases and 32 source/boundary/contracts cover these behaviors.
Option IDs remain uint and raw labels have a 256-code-point limit; over-limit labels
and a larger Python option ID are explicitly recorded typed differences, not parity.

The solver reads an immutable question and returns an option ID or null. It does not
consult the separate reviewed candidate catalog, guess an answer, authenticate source
provenance, confirm an answer, execute storage intents or wire into receive/scheduler
behavior. Known answers, selected options and readiness do not grant it authority.
The separate pure candidate resolver below does not integrate either path into runtime
answer execution. See [strict arithmetic scope and evidence](../dotnet/Lala.Core.Tests/Social/Ark/Arithmetic/README.md).

`ArkReviewedCandidates` now ports the reviewed index and pure resolver from
`ark_candidates.py` and `ark_candidate_data.py`. All 200 text-free rows, seven metadata/
digest fields and 16 user-review annotations match retained Python exactly; there are
zero current static quarantines. Whole-index digest, coverage, IDs/options and annotation
checks run before lookup. The resolver preserves coverage/version/content/quarantine
precedence, requires exactly one matching caller-observed `DataPackage`, and binds the
full question text to its paired option IDs/labels. Observed version fields are not
verified provenance or resource activation.

The 4,865 resolver cases include all 200 IDs in all 24 paired option orders; 42 further
cases exercise whole-index validation. Positive resolution uses synthetic indexes with
fingerprints computed from synthetic text. Real built-in rows, metadata, annotations
and aggregate digest are validated separately; synthetic text against that real index
returns `changed`. This does not establish any production official-text match. Focused
Release verification passed 4,921 tests and the retained Python modules passed 11;
independent source review found no issues. No official text was downloaded or inspected.

Pure matching does not persist evidence, execute receive intents, claim an attempt,
select/send an answer or establish server confirmation. User review remains unconfirmed
candidate evidence. Public callers cannot replace the reviewed index; synthetic index
injection is internal to tests. Runtime receive/storage/scheduler wiring, authenticated
resource activation, official-text matches and live correctness remain open. See
[reviewed candidate boundaries and evidence](../dotnet/Lala.Core.Tests/Social/Ark/Candidates/README.md).

All eighteen State.apply observer positions now have bounded receive composition,
including shop, efficiency, guild actions and Ark after tent. Twenty-six additional
real-State.apply sequences cover 1,414 checkpoints and 38 event kinds. One atomic
publication owns every current projection; even a final Ark failure leaves the old
snapshot and packet count intact. IsCompleteState deliberately stays false: storage
completion, scheduler/commands, remaining State fields and authenticated production
transport are not inferred from receiving packets, and these tests do not establish complete gameplay parity.

`ReceiveAttempt` now connects an already-created read-only byte source to the actual
wire decoder, server dispatcher and all 18 observer positions on one dedicated writer
thread. This internal subset follows `client.py` receive ordering; it supplies no
production socket/dial, credentials, login handshake, writes, commands or authenticated
session. `AccountSession` and Android lifecycle APIs remain unchanged. An observed
`authenticated` game phase is reducer data, not authentication proof.

The constructor is inert and the first run owns cancellation. Reader-owned fixed
buffers cross a bounded channel, defaulting to four 4096-byte chunks plus active
buffers and the decoder's partial frame. Each packet binds inputs to the current
immutable snapshot and a finite injected clock; `ResourceHeld` is always forced true.
Parsed catalogs cannot release the gate. Decode, reduction and commit serialize with
retirement, so failed packets publish no partial snapshot or packet count. Earlier
valid frames remain committed if a later frame in the same read is malformed. The
actual decoder is currently fed bytewise to preserve that behavior; throughput
optimization is deferred. EOF finishes the decoder; cancellation does not finish a
partial frame, and missing required Ark runtime evidence has a fixed failure code.

Attempt lifecycle, current-attempt identity and successful-commit revision remain
separate from observed game state. Display callbacks are ordered but coalesced to one
pending publication, not a lossless packet log. Saved publications require checking
against the owner's current attempt. Retirement is synchronous; cleanup/cancellation
callbacks run outside the state lock. Completion waits for the actual read, joined
writer, observer, transport cleanup and cancellation callbacks. A held participant
keeps completion pending, and cleanup failure reports `CleanupFailed` with
`ResourcesReleased=false`. Repeated runs/disposal share their terminal outcome.

The focused suite passed **283 unique tests**, covering every frame split, direct
coordinator snapshot comparisons, thread ownership, malformed/EOF/error paths,
backpressure, callback/cleanup behavior and cancellation/commit races. Three extra
runs passed 25 selected tests each and added 150 race iterations; those repetitions
are not added to the unique count. A separate synthetic Python receipt sequence was
decoded/applied; source/domain oracle suites remain separate evidence. Independent
final review approved the slice. No full transport/login, resource installation,
real-network throughput or device/server acceptance is established. A receive resource
hold continues accepting receipts and is not Android's terminal `ResourceHeld` result.
See [receive-attempt scope and verification](../dotnet/Lala.Core.Tests/Sessions/Receive/README.md).

`ScriptedHandshake` is a separate internal offline coordinator for verification kind 0,
formal kind 2, role selection, heartbeat and ordered world ACKs. It uses already-decoded
events and synthetic write receipts, not sockets or the receive pump. It requires exact
completed login writes, matching phase/kind responses, a unique current unlocked role,
completed selection, both later initialization observations and completed C12-1 then
C3-2 writes. This deliberately strengthens Python's player-plus-initial-data condition;
early observations reject rather than being saved. No role ID is inferred from a slot.

Receipts bind attempt, connection leg, unique operation, complete byte count and SHA-256.
Wrong, stale, partial, uncertain or replayed receipts retire without retry. Cancellation,
hold and end-input revoke pending writes synchronously; late receipts cannot revive them.
All inputs serialize, and no new event is accepted while a write is pending. A future
transport must own two separate connection legs/decoders, buffer and serialize events,
and map EOF/timeouts/malformed data to end-input. This coordinator has no frame parser
or timers, and local write completion would still not be server confirmation.

It retains no credentials or raw packet; its private pending digest clears on retirement
or completion. Disposing a returned owned wire buffer clears that buffer, not external
caller copies or credential strings. **86 focused** and **2,884 impacted Sessions/Protocol
tests** pass; seven synthetic actual-Python wire vectors regenerate identically.
Independent review verified guards, reduced credential copying and owned-wire parity.
Completion is `ScriptedComplete`, never a production authenticated session. No readiness
boolean, admission/installation hook, AccountSession/ReceiveAttempt integration or Android
`onActive` callback is added. See [offline handshake boundary](dotnet/offline-handshake.md).

### Bounded TCP owner and test-only handshake composition

`a92e68b` adds internal `BoundedTcpTransport`: a one-shot numeric-endpoint socket
owner with bounded read/write buffers and deadlines, one concurrent operation per
direction, terminal retirement and disposal that waits for the actual admitted tasks.
An uncertain write is never replayed. Local complete-byte submission is not peer
receipt, command acceptance or authentication. Its receive-interface loopback tests
retain `ResourceHeld=true`; it is not installed into production login or lifecycle.
Plain TCP and game XOR do not secure credentials. Linux evidence is **33 focused**
and **2,917 impacted Sessions/Protocol passes**, including bounded backpressure,
reset/cancellation and admission races. Linux backlog assertions are not Windows/macOS
evidence. See [bounded transport scope](dotnet/bounded-tcp-transport.md).

`d529af0` adds a **test-only** two-leg harness, not a Core runtime feature. It composes
the existing transport, handshake, decoder and dispatcher using owned loopback peers
and fixed fake credentials. Each leg has a separate serialized decoder owner; exact
write receipts precede later events, including events coalesced in one read. The
verification leg fully ends and disposes before formal connection, and final EOF/tail
checks deliberately define a local test protocol, not real-server behavior. Bounds
cover bytes, events and total deadline. **29 focused** and **2,946 impacted passes**
are Linux loopback evidence, not additional feature-completion counts. Bytewise
decoding remains a throughput limitation. No decoder/socket handoff to `ReceiveAttempt`,
secure credential path, authenticated account lifecycle, resource admission or Android
activation is implemented. See [test-only composition limits](dotnet/test-only-loopback-handshake.md).

Inventory allocation now returns read-only candidates; reservation validation returns
a hypothetical immutable snapshot only after checking the entire batch. Slot ordering,
exclusions, duplicate aggregation, serial identity and source numeric quirks are
retained in 153 Python sequences / 2,032 snapshots. Neither a successful candidate
nor a proposed hold authorizes or installs a live resource acquisition.

Reservation identity/lock/slot queries and release/uncertain/checkpoint/restore now
also have pure immutable proposals. Sixty-eight real-Python sequences cover 1,381
snapshots and 23 lock-query inputs, including repeated proposals, receive composition
and retained checkpoint history. Checkpoints contain exactly five reservation fields;
restore does not restore bag items/readiness, revalidate identity, repair counts or
clear errors. Release retains source per-row clamping and unknown-owner behavior.
No proposal installs or releases a live hold, and uncertain operations do not become
safe because a hypothetical release succeeds. Runtime lifecycle integration remains
outstanding; arbitrary Python dictionary restore patches are not a typed API.

Five combat-resource helpers now derive learned evidence, weapon groups, target
validity, healing effects and field context from explicit current mappings and known
snapshots. Companion skill insertion order is retained across overwrite/remove/re-add
and S15 replacement; imported ambiguous order is rejected rather than guessed. The
1,070 Python cases include 20 receive histories. Field equipment resolution returns
a replacement player snapshot; it does not secretly mutate prior publications or
infer health.

Read-only skill reasons and display rows now preserve early exits, ordered cost/
weapon/appearance/status diagnostics, explicit inventory sufficiency and ordinal
category/SP/ID sorting. The 928 real-Python cases include exact HP-cost rounding
near 2^53 and Int64 limits. Missing SP remains unknown; companion skill validation
skips player item costs. Validation neither acquires reservations nor grants skill-use
authority. See [skill validation evidence](../dotnet/Lala.Core.Tests/Inventory/CombatResourceREADME.md).

Learned, best-skill and food selection now return detached offline candidate intents.
All 1,709 Python observations remain in the corpus: 1,649 supported cases match exactly,
while 60 unsupported food-resource imports have explicit typed rejection rather than
source-parity claims. Food accepts only `hp`/`sp`; nine additional rejection contracts
cover this boundary. Supported cases preserve learned chains, source-key/target order,
ProtocolError-only fallback, food restrictions, exact numeric ties and proposed item
costs. This helper increment initially included only normal attack as the best-skill
fallback; the separate planner below now adds the remaining pure battle selection.
Normal fallback requires known actor/local-role wire identities rather than inventing
IDs. No candidate constructs/sends packets,
installs holds or consumes items. Helper/candidate coordinator and scheduler wiring,
verified catalog activation and account/UI/live acceptance remain gaps. See
[action-candidate boundaries and evidence](../dotnet/Lala.Core.Tests/Inventory/CombatActionCandidatesREADME.md).

`BattleCommandPlanner` now adds the pure `battle_commands.py` slot/identity helpers,
owned-unit enumeration, capture eligibility, all seven action modes and complete round
proposals. The 956 retained-Python observations contain 949 exact in-domain cases and
seven explicit typed identity/import rejections. Known-role ownership/liveness filtering
precedes explicit actor-PID validation before sorting, including singleton sequences.
The battle emission boundary requires an actor PID after earlier candidate errors;
general learned/food helpers keep their existing nullable identity contract. Capture
preserves level/master/equipment rules and uses exact BigInteger arithmetic rather than
overflowing supported Int64 observations. No identity, liveness or catalog trust is guessed.

Each round copies proposed costs into a private immutable Reserved map for subsequent
actors, without changing target HP/SP or installing holds. A failure returns no partial
intents or provisional inventory, and later calls start from the original observations.
Source slot/target ordering, exclusions and error precedence remain explicit. The final
focused suite passed 2,705 tests: 976 new planner tests plus 1,729 existing candidates;
19 retained Python regressions passed. Independent review approved the identity follow-on.
Runtime/catalog activation, executable command dispatch, reservation installation,
scheduler/UI wiring and live acceptance remain open; arbitrary Python object/coercion
parity is not claimed. See [battle action and round boundaries](../dotnet/Lala.Core.Tests/Battle/BattleCommandREADME.md).

`BattleDisplayRules` now ports pure `unit_label` and `attack_lines`. Received names and
fallbacks, 15 normal-attack names and three action-name overrides, action/target/effect
order, duplicates and empty-effective-change text match the retained source. Formatting
uses the current snapshot even for inactive/dead/exited units and never changes state
or interprets a report as authoritative HP/SP. The 116 Python cases cover 12 direct
labels and 155 attack lines under four cultures. The 576 focused tests include 126 new
display tests and 450 existing CombatRules tests; independent review approved this
slice. Observer/UI wiring, full auto-battle, catalog activation and live acceptance
remain gaps. Existing received-event wire types do not imply arbitrary Python scalar
parity. See [battle display evidence](../dotnet/Lala.Core.Tests/Battle/BattleDisplayREADME.md).

`NormalAttackCatalogParser` now ports only `normal_attack_catalog.py`'s `parse_npcs`
and `build_catalog`. Public APIs retain fixed reviewed NPC and ItemData SHA-256 pins,
with ItemData verified/parsed before NPCs in source order. Strict UTF-16LE validation,
record/count/ID/trailing-byte bounds and the source NPC field positions are preserved.
Immutable output carries normal-attack, item-kind, catchability and catch-net facts;
net bonuses use `special == 140` and the first signed Int32 attribute minus 100 without
overflow. These snapshots are data, not capture or attack permission.

The 810 actual-Python vectors cover layout, public-pin rejection, error ordering and
NPC diagnostics. Synthetic layouts substitute Python digest pins only inside restored
test contexts; C# public entrypoints reject every synthetic fixture. Only internal
test helpers bypass digest gates. No actual official-resource success is established.
The 825 focused Release tests pass, with 24 retained Python passes and one existing
asset-dependent skip; independent review approved this slice.

NPC decorator/read diagnostics include safe input digests, record counts, checkpoints
and failure annotations. All 235 NPC truncations preserve exact source wording. Only
247 inherited ItemData truncations before NPC parsing map narrowly to the established
`Catalog record truncated` label; other error messages remain exact, with the public
C# exception type used in diagnostic labels. Existing public parser/reader behavior
is unchanged.
`build_catalog` has no source decorator, and its nested ItemData observation remains
absent. `_source`/`CurrentNormalData`, resource retrieval, runtime activation and complete
parser diagnostics remain gaps. The separate combat-catalog follow-on below reuses
this parser. See [normal-attack catalog scope and evidence](../dotnet/Lala.Core.Tests/Catalogs/NormalAttack/README.md).

`CombatCatalogParser` now adds the pure constants scanner and catalog assembly from
`combat_catalog.py`, reusing the existing SkillData, ItemData and normal-NPC parsers.
Five fixed reviewed public pins cover those three binary inputs and both clear Lua
texts. Strict UTF-8 hashing preserves exact BOM/newline/Unicode bytes and rejects
invalid surrogates. The bounded scanner is not a Lua interpreter: first matches,
enum rules, nested braces and duplicate matrix writes retain the source semantics.
No Lua is executed or decrypted.

Assembly preserves the source stage order, required nonempty names and unique
nonzero skill keys. Immutable results retain all 71 skill fields, five NPC skill slots,
complete item details including attribute effects, 15 character definitions and a
5-by-5 element matrix. Explicit `ToKnowledgeSnapshot` creates the existing unverified
offline DTO; fields absent from that DTO remain in the full parsed catalog. Projection
rejects out-of-range character values and nonfinite weights rather than wrapping or
defaulting. Raw constants retain BigInteger values and source float-overflow behavior.

The 195 actual-Python vectors preserve raw results, errors and diagnostics while
recording typed differences separately. Focused verification passed 2,869 tests,
including 208 new tests; retained Python passed 20 with one existing private-asset
skip. Independent review found no correctness or source-gate blocker. Synthetic pins
are patched only inside restored test contexts; public entrypoints reject synthetic
assets. No official-resource successful parse or runtime acceptance is established.

Inherited SkillData public size-before-hash ordering and its English fingerprint
error differ from Python's hash-first order and Chinese label. Short SkillData
layouts, ItemData truncation labels and value-free enum/float/numeric-limit errors
are separately documented differences. Constants and the overall builder have no
source decorator. NPC diagnostics and secondary reread checkpoints in a diagnosed
parent are retained; nested ItemData/SkillData observations remain missing in this
builder. The newer adapter-only ItemData path below does not change these calls.
`load_verified_catalog`, network/files, normalized caches,
resource activation, UI/session wiring and commands remain gaps. See
[combat catalog scope and evidence](../dotnet/Lala.Core.Tests/Catalogs/Combat/README.md).

`TextDataParser` now ports only `expedition/data.py`'s `parse_text_data`.
The source's more-than-four-byte / 16-MiB size limit, signed count of 1–1,000,000,
UInt32 keys and UInt16 lengths remain. Strict UTF-16LE preserves zero keys, empty
strings, BOMs and every NUL without an unrelated ItemData string cap. Duplicate keys,
odd lengths, malformed Unicode, truncation and trailing bytes fail closed.

`NpcBattleTalkCatalogParser` ports only `parse_known_battle_talk` and `build_catalog`.
The public fixed reviewed SHA-256 is checked before structure, with no pin override.
Counts of 1–20,000 require exact 10-byte rows, nonzero group/text IDs and at most 255
rows per group. Immutable quote groups retain explicit group order, row order and
valid duplicate rows. The builder parses quotes, then TextData, then checks references;
empty referenced strings are valid. It returns groups only and does not certify that
TextData belongs to an official revision or attach decoded text.

All 295 actual decorated-Python vectors retain values, errors and emitted diagnostics
in six hashed gzip resources. Maximum-count and exact 16-MiB inputs use deterministic
recipes with full-result digests. Focused Release verification passed 309 tests
(295 parity, four source hashes, ten contracts); 31 original Python tests passed,
including surrounding runtime tests that do not imply that runtime was ported.
Independent review regenerated the fixtures in memory. Public quote entrypoints reject
all synthetic inputs; successful synthetic quote layouts use internal-only test helpers.
No actual pinned official-resource success is established; later integrated local
verification is recorded below.

The `text-v1` and `npc-battle-talk-known-v1` diagnostics preserve source input names,
digests, counts and failure cursors. The internal helper's optional code-owned input
name defaults to the unchanged `raw`; TextData uses `text_data`. The builder has no
source decorator. Error messages remain exact while Python exception types map to
`CatalogDecodeException`; typed spans, immutable ownership and cooperative cancellation
are explicit differences. Diagnostics remain optional and in memory. Later raw-table
work below adds expedition parsing/name binding; remaining runtime loaders,
`load_verified_catalog`, files/downloads, bundle extraction,
SQLite/cache installation, localization/runtime activation, UI/Android/session wiring
and commands remain gaps. See [TextData and NPC quote scope and evidence](../dotnet/Lala.Core.Tests/Catalogs/TextBattleTalk/README.md).

`SmithDataParser` ports `preview_1275.py`'s `parse_smith_1275` and all three pure
`smith_candidate.py` functions: candidate parsing, timed marking and layout selection.
Signed counts of 0–20,000 require exact 33/35-byte rows; zero rows select 33 first.
The 33-byte map rejects zero/duplicate output IDs, while 35-byte rows require unique
nonzero recipe keys and preserve multiple recipes per output. All returned fields,
material-slot order, duplicate materials and zero amounts remain. Zero material IDs
are omitted; `material_count` validates at most five but does not truncate slots.
Raw results omit `read_only`; timed marking copies rows and sets it when `time_id != 0`.

`StageDataParser` ports only `instance_catalog.py`'s `parse_stages`, retaining all 17
returned fields and consuming every discarded field in the exact 76-byte layout.
Zero IDs remain valid; duplicate rejection follows the complete duplicate row read.
Exact truncation offsets/byte counts and trailing-byte ordering remain, without an
input-size precheck that changes error precedence. Immutable maps explicitly retain
source insertion order separately from frozen lookup.

The 768 actual decorated-Python vectors retain full diagnostics and raw error text
in eight hashed gzip resources. Four successful 20,000-record cases use compact
input recipes and complete ordered-result digests. The 781 focused Release tests
(768 vectors, five source hashes, eight contracts) and 18 original Python tests pass;
independent review reproduced the fixtures and verified recipes/full-result digests.
Typed spans, immutable records, cancellation and CLR exception labels are explicit
differences. Timed marking supports parser-shaped typed rows, not arbitrary Python
extra keys or dynamic `time_id` values. Optional memory-only diagnostics preserve
source `data` input names and nested Smith failure behavior; marking is undecorated.

The `smith-reviewed-v1` structural selector does not certify source identity. The
separate offline adapter below now preserves the 33-byte unmarked ID-keyed map and
35-byte timed-marked array distinction, rather than blindly substituting `ParseRecords`.
Adapter schemas (`smith-new-33-v1`, `smith-new-35-v1`,
`stage-new-76-v1`) remain distinct from parser diagnostic schemas. Other preview
loading, Dungeon/Cooperate parsing/building, runtime/storage/installation,
crafting/entry/transfer/send logic, UI/Android and session wiring remain unported.
No official-resource positive acceptance is established. See [Smith and Stage scope
and evidence](../dotnet/Lala.Core.Tests/Catalogs/SmithStage/README.md).

`CatalogSourceAdapters` now ports the offline `catalog_adapters.py` validation and
composition surface. Immutable contracts validate feature/schema, source name,
lowercase SHA-256, package and version; parsing checks catalog key, package version,
nonempty payload up to 16 MiB and its supplied hash in source order. Exactly five
contracts produce `npc`, `shops`, `crafting`, `scenes`, `items` in that order; extra
payloads are ignored, extra contracts reject, and late failure returns no partial set.
The historical source message “All four” remains unchanged.

The adapter composes actual ItemData, Smith and Stage parsers. NPC/shop derived JSON
can consume `EveV115Indexes.ToJsonUtf8` and retains validated extra fields and their
order. Duplicate properties keep their first position and last value. Results own
immutable ordered maps, rows and detached JSON. The internal adapter-only ItemData
path adds source diagnostics and order while preserving its independent fixed 1296
pin; the outer package version is not forwarded. Caller hashes cannot unlock reviewed
ItemData fields. Existing public ItemData signatures, gates, frozen-map returns and
diagnostics remain unchanged, including missing normal/combat nested instrumentation.

The typed JSON boundary is strict UTF-8/RFC JSON, depth at most 64, finite floats and
valid Unicode escapes. Python `NaN`/`Infinity`, numeric overflow to infinity and lone
surrogates reject explicitly. The 4,300-digit integer limit also applies to ignored or
overwritten values; row/count integers reject booleans/floats, while `schema_version`
retains `true`/`1.0` equality. Valid name/version lengths count Unicode scalars. Typed
contracts/spans, immutable ownership, cooperative cancellation and CLR exception
labels are documented differences, not arbitrary dynamic-Python acceptance.

All 601 decorated-Python vectors retain source results/errors/diagnostics in seven
hashed resources; maximum inputs retain complete ordered-result digests. The **2,274
focused Release passes include older ItemData/catalog, normal-attack and combat
regressions**, not 2,274 new tests. Original Python: 35 passed and one private-bundle
skip. Independent static review and byte-identical fixture regeneration passed.
Feature diagnostics retain a null record count and selected sets report five; nested
successes are suppressed, child failures stay separate, and generic wrapping carries
no inner exception/payload or child cursor into the outer failure.

Supplied hashes, versions, contracts and catalog keys are validation inputs, not
independent provenance. `AssetsReady` and `CanSendPackets` are permanently false.
No runtime/store/network/session/UI/Android integration, ten-table completeness,
extraction/downloads, official-resource positive acceptance or command authority is
established. See [source-adapter scope and evidence](../dotnet/Lala.Core.Tests/Catalogs/SourceAdapters/README.md).

`BundleSourcePreparation` now connects the internal `IResourceSource` seam to
actual DataPackage and MainPackage YooAsset 2.2.5 binary parsing, the ten exact
DataPackage runtime paths and owned verified bundle bytes. Both manifests must pass
identity checks before acquisition. Required paths are `Assets/ResourcesBuild/Data/`
plus `Eve`, `ItemData_C`, `TalkData_C`, `TextData_C`, `SmithData_C`, `ScenesData_C`,
`AdventureData_C`, `AdventureLvData_C`, `NpcData_C` and `NpcCareerData_C`, each with
`.bytes`. This selects sources; it does not extract or validate ten runtime tables.

`DependIDs` are complete sets, not graph edges. Each selected root's dependency list
is unioned once; dependencies excluding roots precede roots, with each group sorted
by bundle name. Cycles, self-references and repeated IDs do not trigger recursive
traversal or blanket rejection. Whole-index bundle changes compare resolved dependency
names, tags, encryption, Unity CRC and file identity. Binary parsing retains all actual
fields, strict UTF-8/booleans, ID and duplicate checks, an 8-MiB / 1,000,000-item limit,
and remaining-byte checks before declared lists are allocated.

Response location/status is checked before Content-Length or body reads. At-most-
64-KiB reads plus an overflow probe verify exact bundle length, MD5 and little-endian
CRC32. Final handles own private immutable byte snapshots, not cache filenames.
Runtime download ceilings remain 24 files / 32 MiB and are checked before acquisition;
a separate conservative 32-MiB total owned-byte cap includes cache hits. Individual
bundle metadata retains the 256-MiB cap. Final version and full-manifest rereads reject
version changes and same-version manifest replacement; invalidated attempts cannot
return stale handles. Content identity uses the existing canonical `ManifestIdentity`
structure and unchanged key derivation, rather than observation-only `CatalogKey`.

Only an injected cache-stream seam exists. Initial corruption is a miss, but a planned
hit that changes is a hard failure rather than an unbudgeted download. Streams are
disposed on success, failure, cancellation and stale attempts. Production filesystem
cache acquisition, persisted receipts, previous-version reuse and atomic publication
remain deferred; this slice accepts no filesystem root, writes nothing and creates
no partial files. A future platform adapter needs safe cancellable regular-file opens
and anchored no-follow writes. An uninstalled HTTP adapter is now separately evidenced
below; no production registration, live-network acceptance or provenance credential is
established.

Focused Resources verification passed **350 tests**, including **81 new tests**:
37 retained actual-Python parser/plan vectors and 44 contracts. Six source hashes,
complete parsed fields, exact ordering and synthetic checksums remain pinned. These
fixtures use allowlisted in-memory HTTP responses and small synthetic payloads, not
actual Unity bundles. Independent review resolved final-observation and unsafe portable
filesystem-adapter issues. The source-only status is now “required bundle sources
verified; no runtime candidate built.” The separate internal owned flow described
below connects this preparer to the native extractor and ten-table decoder. No runtime installation/activation,
freshness/admission credential, `AssetsReady` value, login or packet authority is supplied. The later integrated source-preparation receipt is
recorded below, separately from newer raw-table work. See
[bundle-source scope and evidence](../dotnet/Lala.Core.Tests/Resources/BundleSources/README.md).

`HttpOfficialResourceSource` adds an internal, **uninstalled** implementation of the
neutral `IResourceSource` seam. It owns a narrowly configured client/handler with normal
TLS validation and no credentials, cookies, automatic redirects or decompression. Its
single approved host is bound to preparation before observation; there is no environment
read, arbitrary preconfigured client or host fallback. Original URLs must use that exact
HTTPS origin with no explicit port, userinfo, fragment, percent encoding, backslash or
whitespace. Paths and bundle names are constrained before URI normalization.

Version requests allow numeric cache-busters and at most three same-host/exact-path
manual redirects. Only 400/403/404 permit one canonical query-free retry. Manifests and
bundles never redirect or retry; failures do not fall back to cached metadata. The workflow
follows `observe_official_versions`, not the broader UI checker: HTTP 200 invalid bodies
reject without its `InvalidResourceBody` retry. Raw package/resource-map parsing retains
selected JSON fields, BOM/UTF-16 handling, latest executable selection and the final-array
comma exception. Single-member gzip verifies exact framing, CRC and ISIZE, using one-byte
compressed reads to expose extra members/trailing data. Typed failures and extra JSON-depth/
HTTP-header limits are explicit differences; decorator diagnostics and exact Python error
messages are not claimed.

Headers and version bodies are bounded to **16 KiB**, hash bodies to **eight bytes**,
manifests to **8 MiB**, and resource streams to the existing **32-MiB** retained-source
limit. Strict ASCII Content-Length is checked against actual bytes. Linked **12-second
version / 20-second resource** timeouts cover headers and the entire body lifetime;
caller cancellation stays cancellation. Returned streams own responses and timeout sources,
and failures dispose them. Stable exception categories do not expose URLs, headers,
remote body text or inner transport errors. Existing size/CRC/MD5 and 24-download/32-MiB
preparation quotas remain unchanged.

**86 focused HTTP tests**, **687 impacted Resources tests** and **44 original Python
regressions** pass. The **44 actual-Python raw-parser vectors** and five CRLF-only source
pins regenerate identically; independent review found no confirmed blocker. These are
overlapping counts, not additive new coverage. Fake-handler tests compose manifests,
owned bundles, native Unity extraction, all ten decoders and post-decode reobservation,
including changed versions/manifests, cancellation and disposal failures. No live HTTP,
TLS-network/device/server acceptance or production startup registration is tested.
`SourceStability` now says “observed versions and manifest bytes reobserved after decoding”;
checksums and fresh observations still issue no official provenance, readiness, database
admission or packet permission. See [HTTP scope and evidence](../dotnet/Lala.Core.Tests/Resources/Http/README.md).

The later `3b68ac7` cleanup increment attempts every owned cancellation/disposal step
even after an earlier failure, and preserves a primary version/open/preparation error
with a fixed secondary cleanup marker. Incomplete or reentrant disposal reports stable
`Cleanup` failure rather than false release; successful repeated disposal is idempotent.
Tracked request lifetimes guard timer/caller/shutdown cancellation, prevent throwing
callbacks escaping the timer thread and retire admitted callbacks before CTS disposal.
No arbitrary callback runs under the internal lock. Cleanup can wait for an admitted
callback; there is no universal finite cleanup-deadline claim. **12 adversarial cleanup
tests**, repeated three additional times, and **785 impacted Resources tests** pass;
repetitions and overlapping suites are not new test counts. Independent review approved
the ownership contract. These are fake-handler lifecycle checks, not live TLS acceptance.

`UnityTextAssetExtractor` adds a separate internal offline byte decoder over owned
`VerifiedBundleSource` handles. It supports UnityFS 6/7/8, compression 0/2/3
(uncompressed/raw LZ4/LZ4HC) and front/end block info. Canonical LZ4 termination is
required; the ambiguous `0x200` padding flag is accepted only for the reviewed engine.
SerializedFile 22 is restricted to little-endian Windows64 target 19,
Unity 2021.3.45f2 and embedded class 142 AssetBundle / class 49 TextAsset trees.
The reviewed 58-node/9-node parsing semantics must match; inert node versions and
non-alignment metadata bits are normalized. LZMA, encryption, stripped trees, other
engines/targets/classes and unreviewed layouts fail closed.

AssetPath matching is ordinal and exact. Duplicate matches within/across containers
reject even when they point to the same object. TextAsset names must match the full
filename or its final-extension-free stem. Script bytes retain NUL and invalid UTF-8
without text conversion. File identities include bundle and exact directory names;
CAB basename collisions cannot alias. External PPtrs require explicit source-file,
exact-external-path and target-file bindings, with no fallback or automatic loading.

Extraction accepts 1–24 bundles, at most 64 MiB each / 128 MiB aggregate, with separate
64-MiB per-bundle / 128-MiB aggregate expansion ceilings. Metadata, type trees,
objects, container counts, encoded path bytes and dependencies/externals have further
bounds; script payloads are at most 16 MiB and only the requested script must be
nonempty. These are allocation ceilings, not a peak-RSS guarantee. Streams are scoped,
returned payloads own detached bytes and cancellation is checked throughout bounded
input, decompression and metadata/object/container loops.

The **91 focused passes** include genuine original UnityPy 1.25.4 writer fixtures,
independent lz4 4.4.5 compressed blocks and test-only AssetsTools.NET **[3.0.5]**
byte decoding of retained, hash-verified writer files. Malformed inputs never enter
that package decoder. Core has no runtime decoder package dependency. Only the fixed
common-string table is vendored from the reviewed MIT-licensed upstream source;
[third-party notices](../dotnet/Lala.Core/Resources/UnityTextAssets/THIRD-PARTY-NOTICES.md)
identify it and distinguish package binary evidence from source review. No game
payloads or class databases are retained.

A separate read-only local audit found 22 DataPackage bundles with UnityFS 8,
Unity 2021.3.45f2, SerializedFile 22, embedded class 49/142 trees, header `0x243` and
244 LZ4HC blocks. This is metadata compatibility evidence, not actual-game C#
extraction acceptance. Internal source-to-extraction orchestration is now connected
as described below; production catalog/runtime installation, provenance/admission,
Desktop application execution and Android/AOT remain unverified or unconnected. No resources, login or commands are enabled. See
[Unity extraction scope and evidence](../dotnet/Lala.Core.Tests/Resources/UnityTextAssets/README.md).

A separate local read-only check used the reviewed `a08c719` verification tool on
Windows x64 / .NET **10.0.10**. It extracted `QuestionScoreData_C.bytes` (**94 bytes**)
from **one 1,305-byte UnityFS 8 real bundle**, with both output length and SHA-256
matching independent UnityPy extraction; the tool exited **0**. This is a single
actual-sample extraction receipt, not acceptance of all 22 bundles, the ten-table
pipeline, current HTTPS acquisition, resource admission or complete login. The
standalone tool packaging is not a migrated application feature. No private local
path, game payload or credential is recorded here or added to the repository.

`TalkDataParser` now ports only `npc_talk.py`'s `parse_talk_data`: signed counts,
UInt16 IDs/text lengths, strict UTF-16LE with trailing-NUL removal, voice IDs and all
reserved tail bytes. Source order, duplicate/control rejection precedence and exact
EOF remain. The module's catalog loader and dialogue helpers are still unported.

`ExpeditionCatalogParser` adds task/level parsing, the expedition-specific NPC/career
projection and `attach_names`. Complete 105-byte task rows retain every condition,
recommendation, reward, special reward and signed EXP; 15-byte level rows, source
hashes and whole-row validation remain. Task parsing/EOF precedes levels; the entire
17-byte-row career table/EOF precedes the NPC header. The career-to-original join
allows zero original IDs and absent targets. NPC rows consume two strict strings and
203 fixed fields and are not the reviewed normal-attack projection. Raw expedition
parsers retain their source count/UInt16-string limits, including valid NPC input
above 16 MiB; the composition limit below is not silently imposed on those raw APIs.

`attach_names` reuses TextData, rejects missing/empty names but accepts whitespace and
NUL names, defaults absent areas to empty and appends the TextData hash. Separately,
`OfflineRuntimeTableDecoder` composes only six supplied Talk, Text, Adventure,
AdventureLv, NPC and career tables in relative source order. It checks each required
source at its stage, caps each at 16 MiB and ignores unrelated keys. Its source runtime
name-binding block requires nonblank names and name/area lengths at most 8192 Unicode
codepoints, including Python whitespace U+001C–U+001F. It adds NPC/career hashes to
Adventure hashes, not an invented TextData hash.

The **1,256 unique focused Release passes** comprise **1,239 retained Python vectors**,
five source hashes and twelve contracts. Sixteen gzip resources cover every truncation,
full field/order/diagnostic behavior, precedence and accepted maximum-record recipes
with complete ordered typed-binary result digests. The Python oracle for strict
composition executes the exact source AST name-binding block, excluding enclosing
provenance, fixed-hash/count,
cache and activation steps. Independent final review approved the slice; three oracle
generations reproduced identical resources. Typed keys/immutable catalogs/cancellation
are explicit differences. Source errors retain their messages except NPC's uncaught
Unicode decode error maps to `DecoderFallbackException` without asserting its platform
codec message. Attach/composition invent no diagnosed parser.

The result is labeled `supplied_offline_tables`; provenance, assets-ready, send and
runtime-admitted flags stay false. Existing pins are unchanged. This six-source API remains separate
from the newer ten-table structural candidate and door projection below. Neither
constitutes source admission, installation, cache, transport/login, UI/Android or
official-resource acceptance.
See [required raw-table scope and evidence](../dotnet/Lala.Core.Tests/Catalogs/RequiredTables/README.md).

`OfflineRuntimeCandidateDecoder` now composes the **dynamic structural branch** into
one owned, immutable ten-table candidate. It snapshots Eve, ItemData, Talk, Text,
Smith, Scenes, Adventure, AdventureLv, NPC and career sources in extraction order,
distinguishes missing from empty, caps each at 16 MiB and ignores extra keys, including
claimed provenance. Full Eve parsing keeps its combined-then-per-feature failure
fallback. The new internal ItemData candidate path retains insertion order and source
diagnostics while applying the unchanged public package-version policy and fixed
1296 hash. Synthetic success uses the actual legacy policy; synthetic 1296 inputs reject.

Shop forms 2/3 with kind-3 offers must reference database kind 2 and an owned ItemData
row. Dynamic Smith 33/35 recipes validate every product/material against those same
items, reject zero material counts and retain exact OpenUsed bytes. All recipe
identities remain ordered; duplicate products, including conditional recipes, are
excluded only from the product lookup. Scene parsing precedes door projection and
nonempty scene/talk/text checks. Expedition/career/NPC and strict runtime names follow.
No source rule joins Eve NPC IDs to expedition NPC IDs, so no such join is invented.
`bind_scene_names` skips invalid/missing labels with Python strip/codepoint rules;
`source_scene_label` remains unported.

`EveDoorParser` is deliberately separate from the stricter full Eve parser. Public
`ParsePinned1275` checks the original fixed SHA before layout checks and requires
1,262 scenes; only an internal layout path supports synthetic composition. Ordered
geometry, original name bytes, strict CP950 names, repeated event references,
PlayerTouch records, unsigned conditions, signed effects, conditional convey transfers
and missing convey IDs remain. Destination zero is retained; `DestinationDecoded`
means referential decoding, not route validity or travel permission. Source-supported
overlapping windows, skipped NPC behavior and group/convey-only directory checks
are preserved rather than replaced with full-Eve validation.

Door limits include 32-MiB input, 4,096 scenes and source per-scene record/count limits.
An additional 1,000,000 retained-unit ceiling bounds repeated windows and references:
one of **928 actual-Python door vectors** documents a source-valid safety rejection,
not parity. The lazy 39,564-byte code-owned CP950 mapping is checked against all
**65,792** single-/double-byte Python outcomes. Cancellation and immutable outputs
prevent partial or caller-mutable results; no actual official pinned success is claimed.

The candidate is not `load_verified_bundle_runtime` or static 1275 admission. Static
Eve/adventure hashes, audited counts and the static recipe-count gate are not implemented
by it. `RequiredTablesStructurallyComplete` means only local construction succeeded;
provenance, runtime-admitted, assets-ready and send flags remain false. Fresh official
source provenance/freshness, database-byte admission and runtime installation remain
missing. The newer owned flow below connects extraction-to-table decoding
and post-decode reobservation without supplying those credentials. Optional SkillData,
portal metadata, images, daily/guild/Ark/combat and other catalogs remain unavailable.
The candidate now includes bounded event-only reconciliation and missing-optional
coverage as described below. Standalone optional-portal binding/conflict/coverage
calculations exist, but optional-source acquisition, active-runtime/session/UI/Android
integration and command activation remain outstanding.

**1,102 focused tests** passed (166 candidate and 936 door), then **11,247 impacted
Catalogs + World.Eve tests**, without skips, using the process-only **3 GiB** heap cap.
Candidate evidence retains **157** exact runtime-AST/binding vectors and four source
pins. Its in-memory callback is not a database, and its oracle excludes source
verification, extraction, caches, optional features and activation. Independent
source/security review approved; all three generators reproduced identical artifacts
and **53** related Python tests passed. These are focused/impacted receipts, not an
aggregate or official-resource acceptance claim. See
[ten-table candidate scope](../dotnet/Lala.Core.Tests/Catalogs/RuntimeCandidate/README.md)
and [door projection evidence](../dotnet/Lala.Core.Tests/World/Eve/EveDoorREADME.md).

`OfflineBundleRuntimePreparation` now connects the real internal source preparer,
owned bundle handles, native extractor and all ten structural decoders without a
replacement-decoder callback. Each asset uses its own exact manifest root plus its
listed complete dependency set, not recursive expansion or every selected runtime
root. Unrelated containers cannot change duplicate-path semantics. Every required
TextAsset is extracted before any table is parsed, in the original ten-table order.
A separate conservative **32-MiB aggregate extracted-table cap** supplements existing
per-table/native/acquired-source limits. It can reject unusually large source-valid
tables and is an explicit safety restriction, not parity. External PPtrs reject;
manifest dependencies do not invent an allowlist.

After successful decoding, the flow observes versions, rereads both complete manifest
hash/byte responses, compares original parsed content and observes versions again.
Owner/attempt checks and a final generation-lock return reject late superseded or
invalidated operations. The result is a historical source observation, not a
promise of future server stability. Cache streams are not reopened for extraction;
all bytes are owned and errors/cancellation return no partial result or mutation of
an earlier candidate. Official provenance, database admission, static 1275 admission
and runtime installation remain explicitly unavailable. The newer uninstalled HTTP
adapter uses this same flow in fake-handler tests; production registration, filesystem
cache acquisition/publication, database receipt and AccountSession integration remain absent.

**100 focused Release passes** comprise **19 new flow contracts plus 81 existing
BundleSource cases**. Genuine owned UnityPy 1.25.4 / LZ4HC fixtures cover split roots,
exact dependency isolation, missing/duplicate paths, external references, late raw
decoder errors, aggregate limits, source mutation and post-decode invalidation.
All **11 fixture files** regenerated identically; independent source/security review
approved. This uses the process-only **3 GiB** heap cap and is not actual-game/CDN or
runtime acceptance. See [owned-flow scope and evidence](../dotnet/Lala.Core.Tests/Resources/RuntimeFlow/README.md).

`OfflineEventPortalProjector` separately ports typed event-convey reconciliation.
It retains every conditional destination without executing conditions. Missing
conveys or zero/unknown-stage targets revoke prior position/destination claims;
multiple targets remain undecided. Geometry preserves signed arithmetic before
subtracting one, source rectangles/lines/anchors and the original prior-point behavior,
including retaining a prior point outside new bounds. Conflicting prior destinations
create an immutable `conflicting_event_destination` issue. Callers must carry this
returned issue state forward so repeated reconciliation cannot resurrect that claim.
This replaces source in-place mutation with detached immutable state, not disk storage.

The first event slice included only `boundary_portals.py`'s `touch_bounds`/`door_anchor`
and `portal_evidence_1275.py`'s `_projection_guard`. The subsequent standalone optional
parsers, boundary matching, route conflicts and coverage are described below. Fields
such as `DestinationVerified` describe source cross-checks, not official trust or
travel permission. Bounded event-only observations now reach the candidate and owned
flow, while actual optional portal sources remain unavailable.
Typed optional fields and immutable maps do not promise arbitrary Python dictionary
or mutation-alias parity. Cancellation preserves prior state and returns no partial
projection. No runtime, transport, installation or Android call site is added.

The event slice passed **108 focused tests** (**105 actual-Python vectors plus three
contracts**) and **5,521 impacted tests**. Deterministic fixtures pin event, boundary,
portal-evidence and door sources; independent review approved. Tests retain every
source-present field and row/array counts, including multi-pass conflict cases.
See [event projector tests](../dotnet/Lala.Core.Tests/World/Eve/OfflineEventPortalTests.cs)
and [retained Python fixture generator](../dotnet/Lala.Core.Tests/World/Eve/generate_event_portal_vectors.py).

The optional-portal readers now preserve complete 18-byte StageMap rows, unambiguous
kind-2/3 marker keys, explicit UTF-16LE EveDoorLinks and 12-byte DoorLinkData routes.
Counts are bounded to 100,000 rows, Eve links to 4 MiB, and whole-input lengths are
checked. Unicode decimal digits, supplementary characters, Python whitespace/line
boundaries and the 4,300-digit integer limit are explicit. Marker projection rejects
zero scenes more strictly than the basic StageMap marker parser, matching their
separate source functions. Typed `PortalProjectionException` messages and missing
source decorators are not claimed as exact Python diagnostic parity.

`OfflinePortalReferences` retains source link/route/marker observations and geometry.
`OfflineBoundaryPortals` matches link points or markers to unique physical doors;
link ordinals, marker EventIds and door identities never become interchangeable.
Route-conflict reconciliation removes incompatible claims and annotates related link
evidence, preserves compatible conditional-event subsets and keeps null LinkIndex
separate from a door ID. Source rebuild semantics are deliberately retained: a repeated
Bind can return a rebuilt link claim beside an existing conflict issue because the
event pass skips that issue. A present claim is not automatically conflict-free.

`OfflinePortalCoverage` reports all source-defined scenes, wide marker IDs, source
statuses, unresolved/conditional details, names and reference counts. Its legacy
`SourceRevision=1275` is not a verified current version; `AllSourcesAvailable` means
only that supplied layouts parsed. Work/retention budgets default to 2,000,000
operations and allow 1–10,000,000; shared event copies and conflict candidate retention
are charged. Budget rejection is an explicit safety restriction, not uncapped Python
parity. Cancellation preserves prior immutable state.

This slice passed **100 focused tests** (**95 actual-Python vectors plus five
contracts**) and **5,621 impacted tests**, with deterministic fixtures and independent
review. It does not complete schema-recognition reports, source diagnostic decorators,
actual-resource verification, runtime installation or travel authority.

The ten-table candidate now exposes additive immutable `PortalObservations`, derived
only from its own Eve and ScenesData rows. Bounded event-only binding runs after door
projection and before nonempty required-table checks; coverage runs after the remaining
required-table checks. The candidate fixes the default work budget rather than
accepting a caller override. Optional input keys cannot inject projections or authority:
StageMapData_C, EveDoorLinks and DoorLinkData_C remain explicitly unavailable, both
coverage source statuses stay `missing`, `AllSourcesAvailable` is false and optional
link/route reference counts stay zero. The owned-source flow returns these observations
without changing provenance, database, static-1275 or installation gates.

This integration passed **36 focused tests**: **14 actual-Python vectors**, three new
contracts and 19 existing owned-flow contracts; **5,657 impacted tests** also passed.
Independent review approved deterministic evidence, late-failure/cancellation/supersession
ownership and a separately labeled source-valid amplification input rejected before
large event output allocation. Presence of observations does not make a route actionable.
See [candidate portal contracts](../dotnet/Lala.Core.Tests/Catalogs/RuntimeCandidate/CandidatePortalIntegrationTests.cs).

`RuntimeDatabaseStructuralMatcher` separately checks detached supplied database
observations against a supplied `ManifestIdentity` and expected digest map. It requires
exactly ten unsuffixed expected names in supplied iteration order, then the active key,
bounded ASCII identity JSON, SHA-256 of its **original stored text**, and parsed JSON
equality. Each exact active-version `.bytes` row must have the matching recorded
digest, a non-null 1–16-MiB blob and a matching freshly computed byte hash. The existing
canonical identity string is now available internally; key derivation is unchanged.
No custom identity-key override or metadata-only CatalogKey substitution exists.

Capture copies only ten exact active-version slots and exact memory slices, ignores
optional/stale rows without enumeration, and avoids retaining oversized backing data.
The maximum retained payload is 160 MiB; expected-map iteration rejects an eleventh
entry even when its Count lies. Post-capture mutation cannot alter the snapshot, but
capture does not prove a coherent real database transaction or prevent concurrent
mutation during supply. Zero/negative version IDs are not invented rejection rules.

**140 focused tests** and **2,018 impacted tests** passed. The **128** retained Python
AST cases include **15 structural matches**, exact query-check prefixes and compact
boundary recipes. The oracle uses an inert scripted connection, not SQLite. Parsed
JSON equality remains checked, but no independently reachable hash-matched negative
case is claimed without a SHA collision. Independent review approved. The newer
read-only reader below supplies a bounded transaction snapshot, but filesystem/provider
selection, production integration and binary-schema loading remain separate gaps.
For this matcher, `HasVerifiedProvenance`, `ProvesDatabaseTransaction`, `RuntimeAdmitted`,
`AssetsReady` and `CanSendPackets` remain false. See
[database-match scope and evidence](../dotnet/Lala.Core.Tests/Resources/DatabaseMatch/README.md).

`RuntimeDatabaseSnapshotReader` now accepts a **closed, exclusively supplied, read-only
SQLite-compatible `DbConnection`**, opens it and issues explicit deferred `BEGIN`,
reads the active identity and all ten exact required rows, captures detached bytes,
then `ROLLBACK`s and disposes the connection. It never commits, discovers a provider,
selects a user database, repairs schemas or writes resource data. The supplying adapter
must configure read-only mode and exclusive ownership: generic `DbConnection` cannot
prove filesystem restrictions, honest SQLite execution or isolation. This reader slice
adds no provider or native dependency. Tests use the existing Microsoft.Data.Sqlite 10.0.14 package with
`Mode=ReadOnly`, pooling disabled and newly created temporary databases.

Queries explicitly use `main`, require the four ordinary source-schema tables with
positive root pages and reject views/virtual tables/ambiguity. At most two active-join
or required-row results are requested; duplicate results reject rather than choosing
one. All exact `.bytes` lookups are parameterized against the same active Int64 ID.
Storage classes must be integer/text/blob as appropriate. UTF-8/UTF-16le/UTF-16be database
encoding controls text-byte validation, including embedded NUL, alongside character
bounds. `CASE` projections prevent oversized values entering the managed projection.
A strictly typed `GetValue` byte array is checked for exact nonempty bounded length,
then copied in at-most-64-KiB chunks. No stream API fallback or retry occurs. Retained
payload limits are **160 MiB temporary + 160 MiB detached + at most 16 MiB current
provider value**, not peak RSS; provider/native buffers, caller internals and dead arrays
awaiting GC are outside that bound.

Every command requests a **five-second timeout**, but async execution/cancellation and
timeout latency remain provider-dependent. Uncancelled cleanup attempts rollback even
when a failed `BEGIN` may have executed. Primary exception type, instance and stack are
preserved, with immutable secondary cleanup failures; failed reading, cancellation,
rollback or disposal returns no observation. `CompletedSingleReadTransaction` means
commands and cleanup completed under the provider contract, not a durable certificate.
The detached matcher's `ProvesDatabaseTransaction` stays false; all provenance, runtime
admission, readiness and send flags remain false. The APIs are not installed into
AccountSession or the owned source/runtime flow.

**86 focused** and **2,104 impacted tests** pass with a clean Release build and
independent final review. **52 actual-Python cases** execute unchanged complete source
AST against real temporary SQLite files, separately retaining Python outcomes and
reader capture/match expectations. Ten intentional stricter rejections are labeled;
exact SQL and source short-circuit query order are not claimed. Real-provider tests
check read-only enforcement, unchanged bytes and WAL concurrent-writer coherence;
fault tests cover provider mutation, late cancellation and all cleanup stages.

A real `CASE`-column regression initially hit a native SIGSEGV in the provider's
null-buffer `GetBytes` length probe. Reviewed package source shows its `GetStream`
origin-metadata path is unsuitable for these expression columns. The bounded `GetValue`
contract avoids that path; tests reject any `GetBytes`/`GetStream` call. This resolved
reader regression is unrelated to the historical Python busy-wait assertion failures,
for which no timing fix is claimed. Filesystem/symlink preflight, production database
selection, other read/write APIs, binary table schema loading, official provenance,
admission, static1275/runtime installation and Android/device acceptance remain open.
See [read-only snapshot scope and evidence](../dotnet/Lala.Core.Tests/Resources/DatabaseRead/README.md).

### Complete bounded inventory-write function, still an internal seam

`6cebec4` ports the complete `record_inventory` function into internal
`ResourceInventoryStore`, using an exclusively supplied closed `DbConnection` and
the existing six-table schema. It preserves source member order/POSIX basenames,
optional identity, omitted raw rows, active/previous/parent inventory state and all
seven derived projections: items, Smith, Talk, Text, scenes, Eve NPCs and Eve interactions.
Current/prior parse outcomes, nonempty saved-view collisions, Python scalar ordering
and all report fields remain explicit. Inventory `active_id` is a database selection,
not gameplay activation or permission to send.

One `BEGIN IMMEDIATE` covers schema validation, the allowed `previous_id` evolution,
raw/derived/state writes and commit. Transactional DDL, schema/trigger/index rejection,
stored-byte rehashing and explicit ingestion/query limits are documented stricter Core
contracts. Primary failures survive cleanup failures; a commit exception is `Unknown`,
confirmed commit plus later cleanup failure is `Committed`, and no uncertain write is
automatically retried. The seam chooses no path/provider, accesses no user database
and installs no runtime. Existing parser restrictions, including reviewed ItemData
pins and Eve duplicate-scene rejection, remain in force.

The unchanged Python function, actual parsers and real temporary SQLite produce
**134 scenarios / 234 calls**. Three Python-only invalid types and six stricter Core
rejections are distinguished from ordinary full-report/six-table parity. **312 focused**
and **12,557 impacted tests** pass with a clean Release build under a process-only
3-GiB heap cap; these overlapping suite sizes are not feature counts or a full Core
receipt. Independent source/security review approved the bounded projections. Other
read/load APIs, broader schema migration, path ownership, trusted source admission,
production writer registration and platform/live acceptance remain open. The module
stays `partially_migrated`. See [inventory persistence scope and evidence](../dotnet/Lala.Core.Tests/Resources/Inventory/README.md).

Eve v115 parsing now validates all eleven scene sections before exposing immutable
NPC/interaction indexes. Versions, offsets, record/scene limits, skipped layouts,
truncations and cancellation are checked. The 2,143 exact Python cases are separate
from three deliberate duplicate-scene hardening cases: C# rejects ambiguous IDs
instead of retaining the Python overwrite/count inconsistency. No event execution,
resource activation or retired navigation source is introduced.

The new large Eve fixture family uses deterministic embedded gzip resources rather
than C# byte literals. Compressed and decoded SHA-256 plus byte limits are checked
before JSON consumption, with stable explicit cross-platform manifest names. Old
byte-array fixture APIs and generator output remain unchanged. Every original
synthetic payload and case is retained; missing/corrupt resources fail explicitly.

Parser diagnostics now support bounded in-memory runs/checkpoints, input size/digests,
validated prior-baseline comparison and exact report JSON. The 509 real-Python cases
plus concurrency/cancellation/privacy contracts retain source deduplication and
failure precedence without storing payloads, decoded text, exception messages or
filesystem paths. Metadata/depth admission caps and cancellation protection are
explicit safety differences. Reports cannot enable assets or commands.

Eve typed Parse and serialized Derive entrypoints now automatically use this
in-memory diagnostics layer. The 2,146 actual-Python decorator observations cover
parser names, result counts, variants, raw-input digests and scene/header checkpoints;
the three duplicate-scene hardening cases remain explicit differences, and error
labels use the existing C# exception type. Nested/concurrent sessions, exception
identity, input ownership and cancellation have directed contracts. Success outside
a diagnostic session stays quiet; failure retains a safe observation without keeping
input bytes or exception messages. Normal-NPC, TextData, NPC quote and Smith/Stage
instrumentation are now separately listed above; filesystem persistence, default paths,
public/global ItemData, SkillData and remaining parser instrumentation and runtime
catalog activation remain unimplemented. The internal adapter/candidate ItemData
observations above do not close existing normal-attack/combat diagnostic gaps. Door and dynamic-recipe diagnostics now have
the separately scoped source evidence described above.

### Latest incremental verification evidence

The following are historical slice-specific test receipts, not a combined current
main-branch result or complete module acceptance. This documentation-only update did
not run C# builds or tests, and no platform, live-server or production-storage
acceptance follows from these offline suites.

| Integrated commit | Evidence | Historical verification |
| --- | --- | --- |
| `9f13d37` reservation proposals | `ReservationPlanningParityTests.cs`, `ReservationPlanningContractTests.cs` and generated reservation fixtures under `Lala.Core.Tests/Inventory` | 349 focused tests and 19,541 full Core tests on the isolated earlier-base slice; 68 sequences / 1,381 snapshots. |
| `6b382c2` skill reasons/rows | `CombatSkillValidationParityTests.cs`, `CombatSkillValidationContractTests.cs` and `CombatResourceREADME.md` under `Lala.Core.Tests/Inventory` | 2,029 combined skill-focused tests and 21,487 full Core tests on that slice; 928 new oracle cases. |
| `d8a5ad1` Eve diagnostic wiring | `Lala.Core.Tests/World/Eve/EveDiagnosticTests.cs` and `EveDiagnosticPythonVectors.cs` | 4,848 focused tests and 26,463 full Core tests on the isolated `654118a` base before the subsequent two-test hotfix; 2,146 source diagnostic observations and 26 Python regressions. |
| `974b249` combat action candidates + `a7bea51` hp/sp boundary | `CombatActionCandidateParityTests.cs`, `CombatActionCandidateContractTests.cs` and `CombatActionCandidatesREADME.md` under `Lala.Core.Tests/Inventory` | Final boundary-focused suite: 1,729 passed, including 1,649 supported exact matches, 60 explicit typed rejections and nine new rejection contracts. All 1,709 Python observations remain. The earlier 26,027 full Core pass predates this boundary correction; 19 retained Python regressions were reported separately. No updated unified full-suite result is claimed. |
| `c4489f8` explicit Ark storage plus corruption/schema fixes | `ArkQuestionStorageParityTests.cs`, `ArkQuestionStorageContractTests.cs` and `README.md` under `Lala.Core.Tests/Storage` | Current focused suite: 371 passed, comprising 335 storage-specific tests after nine fixes (256 parity/database-image cases + 79 contracts) and 36 existing matches. Initial 24,633 full Core result on `654118a` plus storage predates those fixes; 104 identity vectors, 149 scenarios / 1,402 operations, three Python-created databases and 36 Python regressions remain. |
| `1863c3b` strict Ark arithmetic | `ArkArithmeticParityTests.cs`, `ArkArithmeticContractTests.cs` and `README.md` under `Lala.Core.Tests/Social/Ark/Arithmetic` | 336 focused Release tests passed: 304 retained-Python cases plus 32 source/boundary/contracts. Five original Python tests passed. No full Core run is claimed for this increment. |
| `5c9e0ea` reviewed Ark candidates | `ArkCandidateParityTests.cs`, `ArkCandidateContractTests.cs` and `README.md` under `Lala.Core.Tests/Social/Ark/Candidates` | 4,921 focused Release tests passed: 4,865 synthetic resolver cases, 42 index cases and additional source/data/contracts; 11 retained Python tests passed. All 200 real text-free rows, seven metadata/digest fields and 16 annotations are checked separately from synthetic positive matches. No full-suite or official-text-match claim is made for this newer increment. |
| `17c7903` + `ced277a` battle planning | `BattleCommandParityTests.cs`, `BattleCommandContractTests.cs` and `BattleCommandREADME.md` under `Lala.Core.Tests/Battle` | 2,705 focused passed: 976 new planner tests plus 1,729 existing candidates; 956 Python observations distinguish 949 exact cases from seven explicit typed rejections. Retained Python regressions: 19 passed. No updated integrated full-suite count is claimed. |
| `6ca75e5` battle display | `BattleDisplayParityTests.cs`, `BattleDisplayContractTests.cs` and `BattleDisplayREADME.md` under `Lala.Core.Tests/Battle` | 576 focused passed: 126 new display tests plus 450 existing CombatRules tests; 116 Python cases, 12 labels and 155 attack lines. No full-suite or runtime/UI acceptance claim. |
| `fe585ca` normal-attack catalog subset | `NormalAttackCatalogTests.cs`, `NormalAttackPythonVectors.cs` and `README.md` under `Lala.Core.Tests/Catalogs/NormalAttack` | 825 focused Release tests passed against 810 actual-Python vectors. Retained Python: 24 passed, one existing asset-dependent skip. Exactly 247 inherited ItemData truncation labels are mapped; 235 NPC truncations retain exact wording. No official-resource success or new combined full-run claim. |
| `4215512` combat constants/catalog assembly | `CombatCatalogTests.cs`, `CombatCatalogPythonVectors.cs` and `README.md` under `Lala.Core.Tests/Catalogs/Combat` | 2,869 focused Catalogs/knowledge tests passed, including 208 new tests and 195 actual-Python vectors. Retained Python: 20 passed, one existing private-asset skip. Explicit inherited gate/error and nested-diagnostic gaps remain; no official-resource success or updated combined full-suite result is claimed. |
| `9843735` TextData/NPC quote subset | `TextBattleTalkCatalogTests.cs`, `TextBattleTalkPythonVectors.cs` and `README.md` under `Lala.Core.Tests/Catalogs/TextBattleTalk` | 309 focused Release passes: 295 actual decorated-Python vectors, four source hashes and ten contracts; 31 original Python passes. Independent review regenerated all six resources. Typed API/exception differences remain explicit; no official-source positive acceptance, runtime/storage migration or new combined full-suite claim. |
| `61a4451` Smith/Stage dependencies | `SmithStageCatalogTests.cs`, `SmithStagePythonVectors.cs` and `README.md` under `Lala.Core.Tests/Catalogs/SmithStage` | 781 focused Release passes: 768 actual decorated-Python vectors, five source hashes and eight contracts; 18 original Python passes. Eight gzip resources and four maximum-result digests independently reviewed. No adapter/runtime/store migration or official-source positive acceptance; the later integrated local receipt is recorded below. |
| `3e32aab` five-feature source adapters | `CatalogSourceAdapterTests.cs`, `SourceAdapterPythonVectors.cs` and `README.md` under `Lala.Core.Tests/Catalogs/SourceAdapters` | 601 actual decorated-Python vectors; 2,274 focused Release passes include existing ItemData/catalog, normal-attack and combat regressions. Original Python: 35 passed, one private-bundle skip. Seven fixture resources regenerated identically; review passed. Internal-only ItemData diagnostics and explicit typed JSON bounds do not imply runtime or official-resource acceptance. The later integrated local receipt is recorded below. |
| `e22e64e` internal receive-only integration | `ReceiveAttemptTests.cs` and `README.md` under `Lala.Core.Tests/Sessions/Receive` | 283 unique focused tests passed; three additional 25-test repetitions add 150 cancellation/commit race iterations without increasing the unique count. Separate synthetic Python receipt decode/apply and independent final review passed. No production transport/login/send/resource activation; the later integrated local receipt is recorded below. |
| `fe5e61b` required bundle-source preparation | `BundleSourceParityTests.cs`, `BundleSourcePreparationTests.cs`, `bundle_sources.json` and `README.md` under `Lala.Core.Tests/Resources/BundleSources` | 350 focused Resources passes include 81 new tests: 37 actual-Python parser/plan vectors and 44 contracts. Six source pins and complete synthetic index/plan/checksum evidence remain; no production HTTPS/provenance, filesystem cache publication, extraction/runtime/admission or newer combined full count claimed. |
| `3abe07a` required Talk/expedition tables | `RequiredTableParityTests.cs`, `RequiredTableBoundaryTests.cs`, `RequiredTableOracleCases.cs` and `README.md` under `Lala.Core.Tests/Catalogs/RequiredTables` | 1,256 unique focused Release passes: 1,239 retained actual-Python vectors, five source hashes and twelve contracts. Independent final review and three identical generations; no full ten-table runtime, source admission or newer aggregate count claimed. |
| `daf4953` bounded UnityFS/TextAsset extraction | `UnityTextAssetTests.cs`, `UnityBoundariesTests.cs`, `UnityIndependentDecoderTests.cs` and `README.md` under `Lala.Core.Tests/Resources/UnityTextAssets` | 91 focused passes with genuine owned UnityPy writer fixtures and independent test-only AssetsTools.NET 3.0.5 byte decoding. Explicit format/ownership/aggregate-budget limits; local actual-resource metadata compatibility is not actual-game C# extraction, pipeline integration or Android/AOT acceptance. The later process-capped aggregate receipt is recorded below. |
| `3338585` owned ten-table structural candidate and doors | `RuntimeCandidateTests.cs`, `RuntimeCandidateOracleCases.cs` and `README.md` under `Lala.Core.Tests/Catalogs/RuntimeCandidate`; `EveDoorTests.cs`, `EveDoorPythonVectors.cs` and `EveDoorREADME.md` under `Lala.Core.Tests/World/Eve` | 1,102 focused passes (166 candidate / 936 door) and 11,247 impacted passes, using the process-only 3-GiB cap. 157 candidate and 928 door Python vectors retain one explicit door-budget safety divergence; 53 related Python tests passed, independent review approved and three generators reproduced exactly. Structural completeness is not runtime admission; aggregate evidence follows below. |
| `4d70eb0` owned source-to-runtime structural flow | `OfflineBundleRuntimePreparationTests.cs`, genuine owned UnityFS fixtures and `README.md` under `Lala.Core.Tests/Resources/RuntimeFlow` | 100 focused passes: 19 new contracts plus 81 existing BundleSource cases, under the process-only 3-GiB cap. Eleven retained fixture files regenerated identically; independent review approved. Post-decode scripted reobservation and owned extraction do not issue official provenance, admission or active-runtime authority. |
| `1ebc354` separate immutable event-portal projection | `OfflineEventPortalTests.cs`, `EventPortalPythonVectors.cs` and `generate_event_portal_vectors.py` under `Lala.Core.Tests/World/Eve` | 108 focused passes (105 actual-Python vectors and three contracts), then 5,521 impacted passes; independent review and deterministic fixtures. Typed carried-forward issues preserve conflicts; no candidate installation, broader boundary reconciliation, route coverage or travel authority. |
| `6e44908` optional portal parsers/bindings/coverage | `OfflineBoundaryPortalTests.cs`, `BoundaryPortalPythonVectors.cs` and `generate_boundary_portal_vectors.py` under `Lala.Core.Tests/World/Eve` | 100 focused passes (95 actual-Python vectors plus five contracts) and 5,621 impacted passes; deterministic source/fixture pins and independent review. Typed safety budgets, source-compatible repeated-conflict behavior and diagnostic gaps remain explicit. |
| `7d04773` owned database structural matcher | `RuntimeDatabaseStructuralMatcherTests.cs`, `DatabaseMatchPythonVectors.cs`, fixture evidence and `README.md` under `Lala.Core.Tests/Resources/DatabaseMatch` | 140 focused passes and 2,018 impacted passes; 128 actual-Python AST cases include 15 matches. Independent review approved; scripted query traces and supplied snapshots do not prove real database transactions, source authority or admission. |
| `3445831` event-only candidate observations | `CandidatePortalIntegrationTests.cs`, `CandidatePortalOracleCases.cs` and retained fixture generator under `Lala.Core.Tests/Catalogs/RuntimeCandidate`; owned-flow integration assertions | 36 focused passes include 14 actual-Python vectors, three new contracts and 19 existing flow contracts; 5,657 impacted passes. Independent review approved. Candidate budget is fixed; optional metadata stays missing and all authority flags remain false. |
| `850b7af` isolated scripted handshake | `ScriptedHandshakeTests.cs`, seven `python-vectors.json` rows under `Lala.Core.Tests/Sessions/Handshake`, and `docs/dotnet/offline-handshake.md` | 86 focused and 2,884 impacted passes; deterministic actual-Python wire vectors and independent review. Strict synthetic phase/receipt ordering is not Python lifecycle parity, production login or transport ownership. |
| `6d61601` uninstalled HTTP source/raw parsers | `HttpResourceSourceTests.cs`, `HttpPythonVectors.cs`, generator and `README.md` under `Lala.Core.Tests/Resources/Http` | 86 focused and 687 impacted Resources passes; 44 retained actual-Python parser vectors, five source pins and 44 original Python passes. Independent review and fake-handler full-flow checks do not establish live HTTP/TLS, official provenance or admission. |
| `3848459` read-only transactional snapshot | `RuntimeDatabaseSnapshotReaderTests.cs`, `DatabaseReadPythonParityTests.cs`, fixture evidence and `README.md` under `Lala.Core.Tests/Resources/DatabaseRead` | 86 focused and 2,104 impacted passes; 52 real-SQLite Python cases distinguish original results and ten stricter capture rejections. Final review approved bounded GetValue provider regression, WAL coherence and failure/cleanup guards. Caller-configured read-only/exclusive provider contract is not provenance or admission. |
| `a92e68b` uninstalled bounded TCP owner | `BoundedTcpTransportTests.cs` and `docs/dotnet/bounded-tcp-transport.md` | 33 focused and 2,917 impacted Linux loopback passes; numeric endpoint, bounded operations, uncertain writes, retirement and receive holds. No production login, secure credentials or Windows/macOS runtime acceptance. |
| `d529af0` test-only two-leg handshake composition | `LocalHandshakeCompositionTests.cs`, `LocalHandshakeHarness.cs` and `docs/dotnet/test-only-loopback-handshake.md` | 29 focused and 2,946 impacted Linux loopback passes. Test-only ordered composition, synthetic peers/credentials and explicit EOF protocol; no runtime feature, lossless receive handoff or authenticated lifecycle. |
| `6cebec4` complete bounded inventory-write function | Persistence/projection tests, fixture evidence and `README.md` under `Lala.Core.Tests/Resources/Inventory` | 134 unchanged-Python scenarios / 234 real-SQLite calls; 312 focused and 12,557 impacted passes under the process-only 3-GiB cap. Six-table writes and seven projections, with explicit stricter bounds/schema/transaction behavior; no production database writer or resource activation. |
| `3b68ac7` exhaustive HTTP cleanup | `HttpCleanupTests.cs`, `ResourceRequestLifetime.cs` and HTTP test `README.md` | 12 adversarial cleanup tests plus three repeats and 785 impacted Resources passes. Independent review of exhaustive ownership, primary-error preservation and tracked callback retirement; no universal cleanup deadline or live TLS evidence. |
| `cafdfb8` uninstalled resource-only admission owner | `ResourceRuntimeOwnerTests.cs` and `docs/dotnet-resource-runtime-owner.md` | 24 focused tests passed in three runs; independent final review approved. Owned default HTTPS, real read-only SQLite match and final manifest recheck are implemented, with exact current-reference/generation admission. Offline tests remain non-authorizing; no successful live TLS receipt, bootstrap, login/packets or Android native-load acceptance. Final aggregate is pending. |

Inventory status remains partial for the subset modules below. Desktop `network/client.py`
(internal receive, isolated scripted handshake and uninstalled bounded TCP owner;
two-leg composition remains test-only), `network/commands.py`
(select-role guards only), `battle_commands.py`
(pure action/round planning), `storage/ark_questions.py` (explicit offline store),
`services/ark_first_answer.py` (strict arithmetic), `services/ark_candidates.py` (pure
reviewed resolver), `services/ark_candidate_data.py` (text-free reviewed index),
`services/world/normal_attack_catalog.py` (offline parse/build),
`services/expedition/data.py` (TextData/task/level/NPC/name-binding subsets),
`services/world/npc_battle_catalog.py`
(offline quote parse/build), `services/world/preview_1275.py` (Smith 33-byte parsing
only), `services/instance_catalog.py` (Stage parsing only),
`services/world/npc_talk.py` (Talk decoding only),
`services/world/unity_textasset.py` (bounded internal binary extraction),
`services/world/doors_1275.py` (bounded door projection) and
`services/world/scene_names_1275.py` (typed scene-name binding only) move from not migrated
to partially migrated. `services/world/smith_candidate.py` is ported offline for its
three pure functions within the documented typed API. `services/world/catalog_adapters.py`
is also ported offline for its bounded validation/composition surface; runtime
integration and official-source acceptance remain separate. The summary is now
553 not migrated, 139 partially migrated and 4 ported offline. Android inventory and
reservation entries share identical source hashes and receive the same bounded evidence. Android network-client/commands/protocol, combat-resource, battle-command,
combat/display, Eve, expedition-data, preview, Smith-candidate, instance-catalog,
ItemData and catalog-adapter hashes differ, so they stay unreconciled. The baseline has
no Android `storage/ark_questions.py`, `services/ark_first_answer.py`, `services/ark_candidates.py`,
`services/ark_candidate_data.py`, `services/world/normal_attack_catalog.py` or
`services/world/npc_battle_catalog.py` entry.
The manifest-index tool's binary parser subset, `official_manifest_sync.py`,
`official_bundle_download.py`, `official_incremental_sync.py` and
`world/bundle_runtime_1275.py` now have partial source-preparation evidence;
`world/dynamic_bundle_runtime.py` remains partial with expanded internal preparation
scope. All six corresponding Android source hashes differ, so none is mirrored. The newer
Talk/expedition/raw-runtime decoder and Unity TextAsset sources also differ from
Android; they remain partial desktop evidence only. Door, dynamic-runtime and ItemData
hashes also differ. The scene-name source hash is identical, so its narrow binding
subset is mirrored to Android without claiming an Android call site or device pass.
The event projector, boundary geometry and projection-guard subsets are also partial;
all three corresponding Android source hashes are identical, so the same bounded
evidence is mirrored. The later coverage module also has an identical Android hash
and receives partial evidence. Portal-links, portal-schema and resource-database hashes
differ, so those newer desktop partial entries are not mirrored. Remaining typed/API,
source-diagnostic and runtime gaps are documented per module.
`IsCompleteState` remains false. The offline store, arithmetic solver and reviewed resolver do not establish Ark runtime
persistence or command activation, and none of these slices establishes full migration
or full runtime acceptance. Current combined verification is recorded below.

The new raw-version/HTTP mappings remain partial in `official_version.py`,
`official_source.py`, `official_manifest_sync.py` and `official_bundle_download.py`;
the source-preparation/runtime modules retain all admission and installation gaps.
`resource_database.py` now includes the read-only transaction subset and complete
bounded `record_inventory` function, not the remaining module APIs or runtime integration;
its Android hash differs and is not mirrored. The HTTP cleanup increment expands only
the existing partial adapter mappings, without changing module statuses.
`game_version_gate.py` moves to partial only for the resource/database comparison
composition in `cafdfb8`; its login verdicts and full source module are not ported.
The same owner expands the existing partial `dynamic_bundle_runtime.py` and
`resource_database.py` mappings without installing production runtime globals.
All three actual desktop source hashes were checked against the unchanged inventoried
files; their Android source hashes differ, so no owner mapping is mirrored.
`official_resource_sync.py` has an identical Android hash and receives only the shared
Core observation subset, not an Android host callsite. The other HTTP/handshake source
hashes differ (or no matching Android module exists), so they are not mirrored.

### Integrated verification for published commit `9e0a04f`

The integrated tree after `f939c4f` passes **28,865 Core Release tests**, with no
failures or skips, using standard build/test settings. Android lifecycle remains
**59/59**; Desktop Release builds with zero warnings/errors and its offline inspector
passes **9 checks**. The retained Python suite runs **2,273 tests**, with **216**
existing platform/headless skips. Strict repository audit and whitespace checks pass.
Remote verification for published commit `9e0a04f` is also green in
[CI run 42403253359](https://github.com/blesses0603/WLRe_lala/actions/runs/42403253359)
and [CI run 42403254318](https://github.com/blesses0603/WLRe_lala/actions/runs/42403254318).
Windows, macOS and Linux each passed 28,865 Core tests and 59 lifecycle tests, built
Desktop with zero warnings/errors and passed all nine offline inspector checks.
The Android validation APK build succeeded. These receipts apply to `9e0a04f`, not
the newer reviewed-candidate, battle-planning or display increments; their focused
evidence is listed above.

### Integrated verification for published commit `796d96d`

The subsequent integrated tree through `ced277a`, published as `796d96d`, passes
**34,888 Core Release tests**, with zero failures/skips. Android lifecycle passes
**59/59**; Desktop Release has zero warnings/errors and **9** offline self-test checks
pass. Retained Python runs **2,273** tests with **216** existing platform/headless
skips, and strict repository audit passes.

Remote [.NET CI run 42405102704](https://github.com/blesses0603/WLRe_lala/actions/runs/42405102704)
and [Python CI run 42405102776](https://github.com/blesses0603/WLRe_lala/actions/runs/42405102776)
are both green for `796d96d`. Windows, macOS and Linux each pass 34,888 Core tests,
59 lifecycle tests, Desktop builds with zero warnings/errors and nine offline self-test
checks. The Android validation APK build also succeeds. These receipts exclude the
newer `fe585ca` normal-attack/NPC and `4215512` combat-catalog increments. The newer combined local verification is recorded below; these remote receipts
apply only to the published commit. CI builds and offline tests do not establish installation,
device, official-resource success or live-server acceptance.

The final Ark storage review adds nine corruption/schema regressions: contradictory
registered candidate/attempt evidence fails closed, all identity predicates explicitly
use BINARY comparison, and trigger-owner matching follows SQLite's case-insensitive
identifier semantics. Nonquarantined and already-quarantined cases, unregistered
attempts, all three identity columns and all three trigger owners are covered.
The focused Storage suite is **371/371** (335 storage-specific plus 36 existing named
matches), and independent source review approved the fixes. At that increment Core had no
database provider dependency: Microsoft.Data.Sqlite was test-only; production connection/path,
current-session validation and memory-intent execution remain host integration gaps.

All changed generated C# fixtures retain the existing 500,000-byte limit under both
LF and CRLF. Android source, AccountSession and connection/lifecycle public APIs are
unchanged by this increment. The strict arithmetic helper and reviewed candidate
intents remain separate from sending or confirming answers. `IsCompleteState` stays
false; the migration remains a Draft and is not ready to replace the Python client.

### Integrated verification for published commit `9f42b6f` (8.0.15)

The integrated tree through `74f925e`, published as `9f42b6f`, passes
**35,923 Core Release tests** with zero failures/skips under the standard command,
without GC or execution-policy overrides.
Lifecycle remains **59/59**, Desktop builds with zero warnings/errors and its **9**
offline checks pass. Retained Python runs **2,273** tests with **216** existing skips.
Remote [.NET CI run 42409260253](https://github.com/blesses0603/WLRe_lala/actions/runs/42409260253)
is green for `9f42b6f`: Windows, macOS and Linux each pass **35,923 Core tests**,
**59 lifecycle tests** and **9 offline self-tests**, with Desktop builds reporting
zero warnings/errors. The Android validation APK build also succeeds.

[Python CI run 42409260256](https://github.com/blesses0603/WLRe_lala/actions/runs/42409260256)
is green after rerunning only its failed macOS job, without changing the commit.
The initial `test_busy_database_fails_closed_with_bounded_wait` failure measured
**1.075378 seconds** against the existing **1.0-second** threshold. The unchanged
[macOS rerun job 128515192188](https://github.com/blesses0603/WLRe_lala/actions/runs/42409260256/job/128515192188)
succeeded with **2,273 tests** and **194 existing skips**. No Python source or test
threshold was changed, and the successful rerun does not establish or fix the timing
failure's root cause. These published-commit receipts exclude the newer `9843735`
TextData/NPC quote increment, its later test-memory changes and the Smith/Stage slice.

Earlier aggregate runs were terminated (diagnostic exit 137, about 4.3 GiB peak
testhost RSS). Test-only changes keep NPC/EVE JSON out of theory display names and
resolve bounded scalar indices at execution. All 2,146 EVE cases per theory and all
52 EVE gzip resources remain unchanged. A temporary process-only 2 GiB diagnostic
run exposed seven OutOfMemory exceptions in the combat-action contract fixture
loader, which reparsed a 7,109,103-byte corpus for 19 tests. It now caches only the
detached 5,281-byte baseline row and gives each test a fresh deep clone. Added
index/isolation checks preserve coverage; independent review and deterministic
generator replay passed. No production behavior, test expectations, GC settings,
parallelism, size limits, CI policy or fixtures were relaxed. The final standard
full-suite run passes; no claim is made that every earlier termination has a
uniquely established cause.

This increment does not implement runtime catalog installation or official-source
positive acceptance. Public/global ItemData and SkillData automatic diagnostics and
the documented legacy SkillData admission-order differences remain outstanding; the
newer internal adapter-only ItemData path is separately scoped above. Android and
AccountSession are unchanged, and `IsCompleteState` remains false.

### Integrated TextData/NPC quote verification through `d4c80ee`

The `9843735` slice retains its **309 focused passes** above. The integrated tree
through `d4c80ee` now passes **36,235 Core Release tests** under the standard command.
This is a local receipt, not new remote CI, and excludes the later `61a4451` Smith/Stage
increment. Before the test-only changes below, the first standard run ended in a
testhost crash. A temporary process-only **2 GiB diagnostic run** completed **36,232
results** with **three OutOfMemory failures** in legacy fixture loading or assertion
JSON formatting. This failed diagnostic run is not a standard-command pass or proof
that the text/quote slice caused the memory pressure.

Test-only follow-ons `eb84db5` and `d4c80ee` cache a detached battle-command baseline
row with fresh deep clones per test and defer inventory assertion-message formatting
until an assertion fails. Added contracts cover nested mutation isolation and ensure
passing assertions do not format messages, while failures preserve their full xUnit
message. Equality checks, expected values, fixture coverage and failure thresholds
remain unchanged. No production, Python, GC, parallelism or CI-policy change is made.
The standard full-suite pass after these changes does not prove a unique cause for
every earlier termination or establish runtime/resource activation or official-source
acceptance. The subsequent aggregate receipt including Smith/Stage follows.

### Integrated verification for published commit `68770ae` (8.0.16)

The integrated tree including Smith/Stage, published as `68770ae`, passes **37,016
Core Release tests** under the standard command, with **zero failures or skips** and
**no GC overrides**. This local result is separate from the published `9f42b6f`
(8.0.15) remote CI receipts above. Final lifecycle **59/59**, Desktop Release **zero
warnings/errors** and **9** offline self-tests pass. The retained Python suite runs **2,273 tests**, with **216**
existing platform/headless skips, using the established dependency-equipped test
environment. An initial global-interpreter invocation lacked UnityPy and is not
counted as a passing run. Strict repository audit and whitespace checks pass.
Remote [.NET CI run 42410768620](https://github.com/blesses0603/WLRe_lala/actions/runs/42410768620)
and [Python CI run 42410768807](https://github.com/blesses0603/WLRe_lala/actions/runs/42410768807)
are both green for `68770ae`. Windows, macOS and Linux each pass **37,016 Core tests**,
**59 lifecycle tests** and **9 offline self-tests**, with Desktop builds reporting
zero warnings/errors. The Android validation APK build succeeds. These receipts
exclude the newer `3e32aab` source-adapter and `e22e64e` receive-pump slices; their
subsequent local Core receipt follows. No runtime/storage wiring
or official-resource positive acceptance follows from CI; `IsCompleteState` remains false.

### Integrated adapter/receive verification through `e22e64e`

The combined source-adapter and receive-only tree through `e22e64e` passes **37,918
Core Release tests**, with **zero failures or skips** under standard settings. This
is a local Core receipt, separate from published `68770ae` remote/platform CI. It
excludes the later `fe5e61b` manifest/source-preparation increment. No newer platform,
production transport/login, runtime/resource activation or official-source acceptance
is established by this result; `IsCompleteState` remains false.

### Required bundle-source candidate verification (8.0.17)

The later tree includes `fe5e61b` and retains both source-adapter and bundle-source
fixture resource entries. The integrated standard Release run passes **37,999 Core tests**, zero failures/skips.
This receipt excludes the later `3abe07a` required raw-table slice.
Lifecycle **59/59**, Desktop zero warnings/errors and **9** offline checks pass.
Retained Python runs **2,273 tests** with **216** existing skips in the established
test environment. Strict repository audit and whitespace checks pass. The earlier
**37,918** receipt excludes this increment; **350 Resources** remains focused evidence,
not a count of new tests. The project-resource merge retained both entries; no
production behavior or test policy was relaxed. This historical subset is included
in the later published `231f894`; its remote CI status is recorded below. No genuine Unity extraction, production source provenance,
secure filesystem cache publication, runtime admission or live transport/login is
established by this result.

### Integrated required raw-table verification through `d58d6a8`

The integrated tree including `3abe07a` and test-only `d58d6a8` passes **39,255 Core
Release tests**, with **zero failures or skips**, using `--no-build` against the exact
compiled assembly and a process-only `DOTNET_GCHeapHardLimit=0xC0000000` (**3 GiB**).
Peak testhost RSS was **3,245,384 KiB**. This is a local, process-capped receipt, **not
a standard-setting pass**. New standard runs ended in host termination without
assertion failures; no unique root cause is established or claimed fixed. Repository
and CI GC settings and parallel-execution policies remain unchanged. The later
published standard-setting remote receipt is recorded below.

Test-only `d58d6a8` changes **55** pure `DeepEquals` assertion messages across **49
files** to use the existing `LazyAssert`, deferring message construction until
failure while leaving equality evaluation eager. Independent review confirmed that the edits are exactly reversible and checked
side effects and captured values. The NpcShop message containing
`index++` remains eager. Cases, expected strings and fixture hashes are unchanged;
no production behavior or test acceptance threshold is relaxed.

Retained Python runs **2,273 tests** with **216** existing skips, and strict repository
audit passes. Lifecycle **59/59**, Desktop **9** offline checks and zero build
warnings/errors had last been verified before RequiredTables; refreshed results for
the later integrated tree are recorded below. The prior standard **37,999** source-preparation receipt excludes
RequiredTables, and **1,256** remains its unique focused decoder count, not the
aggregate total. Existing source-preparation and required-table fixture resource
entries are both preserved. This `d58d6a8` receipt excludes the later Unity extractor.
No runtime admission follows from fixture registration or successful synthetic
decoding; `IsCompleteState` remains false.

### Integrated verification for published commit `231f894` (8.0.17)

The integrated tree through `daf4953`, published as `231f894` with the same final
`c99a136` tree, includes the bounded Unity extractor and passes **39,346 Core
Release tests**, with **zero failures or skips**, under a process-only **3 GiB** heap
budget. The build reports **zero warnings/errors**. This is a local process-capped
result, not a standard-setting local pass; the completed standard-setting remote
.NET receipt and failed Python workflow results are recorded below. The prior
**39,255** receipt excludes the extractor. No unique cause for the earlier standard
host terminations is claimed fixed, and repository/CI GC policy is unchanged.

Final local refreshes on `daf4953` pass **59/59 lifecycle tests**, Desktop Release
with **zero warnings/errors** and **9 offline self-tests**. Retained Python runs
**2,273 tests** with **216 existing skips**, and strict repository audit passes.
These local receipts remain separate from the remote CI results below. The 91-test focused
extraction receipt and matching real metadata do not establish actual-game payload
extraction, complete resource-pipeline wiring, runtime admission or Android/AOT acceptance.
`IsCompleteState` remains false.

Published `231f894` [.NET CI run 42416341780](https://github.com/blesses0603/WLRe_lala/actions/runs/42416341780)
is fully green. Windows, macOS and Linux each pass **39,346 Core tests**, **59 lifecycle
tests** and **9 Desktop self-tests** under standard settings, with Desktop reporting
zero warnings/errors. The Android validation APK job also passes. This is the
standard-setting remote .NET receipt; it does not change the process-capped settings
of the local run or establish a unique cause for the earlier local host terminations.

[Python CI run 42416341769](https://github.com/blesses0603/WLRe_lala/actions/runs/42416341769)
completed with Windows and Ubuntu passing, but macOS failed the existing one-second
SQLite bounded-wait assertion: **1.009152792 seconds** exceeded **1.0 second**.
The single [macOS retry job 128537032310](https://github.com/blesses0603/WLRe_lala/actions/runs/42416341769/job/128537032310)
also failed that assertion at **1.171469625 seconds**. The Python workflow is not
green. No further reruns or threshold/production changes are claimed; later
diagnostic observations are recorded below and the timing cause is not fixed. These published-commit receipts exclude
`3338585` and the later flow/event slices.

### Integrated ten-table candidate verification through `3338585`

The newer integrated tree passes **40,448 Core Release tests**, with **zero failures
or skips** and **zero build warnings/errors**, under the process-only
`DOTNET_GCHeapHardLimit=0xC0000000` (**3 GiB**). Repository GC/CI policy is unchanged.
This is a local capped aggregate, not a standard-setting local pass or a new remote
CI receipt. The earlier published **39,346** total excludes this increment.
The full retained Python suite runs **2,273 tests** with **216 existing skips**, and
strict repository audit passes with **287 checked links**. These final local receipts
are separate from the **53** related Python passes above and published `231f894` CI.
No new lifecycle/Desktop result for `3338585` is asserted here. A complete structural
candidate still does not establish verified source extraction, runtime admission/activation,
official-resource success or live acceptance. `IsCompleteState` remains false.

### Integrated verification for published commit `19430f5` (8.0.18)

The integrated tree through `f4b8eb9`, published as `19430f5`, includes `4d70eb0`
and `1ebc354` and passes **40,575 Core Release tests**, with **zero failures/skips** and **zero build warnings/errors**, under the
process-only `DOTNET_GCHeapHardLimit=0xC0000000` (**3 GiB**). This remains a local
capped aggregate, not a standard-setting local or new remote CI pass. The earlier
**40,448** total excludes both increments; focused/impacted counts are separate.

Final local checks pass **59/59 lifecycle tests**, Desktop Release with **zero
warnings/errors** and **9 offline self-tests**. The retained Python suite runs
**2,273 tests** with **216 existing skips**; strict repository audit passes with
**289 checked links**. These results do not resolve the published 8.0.17 macOS
Python CI failures on the earlier commit above; the newer published CI receipt
follows below.

Diagnostic-only `f4b8eb9` adds a macOS pretest observation step using a fresh temporary
SQLite database, a bounded worker, SQLite build options and measured busy/sleep times.
It does not open application databases or change production code, existing assertions,
timing thresholds, GC policy or regression failure behavior. The step collects evidence;
it is not a timing fix or proof of a unique root cause.

Structural flow and separate geometric evidence still do not establish official
provenance, database admission, runtime installation/activation, actual-game extraction,
Android/AOT or live acceptance. `IsCompleteState` remains false.

Published `19430f5` [.NET CI run 42417788093](https://github.com/blesses0603/WLRe_lala/actions/runs/42417788093)
and [Python CI run 42417788272](https://github.com/blesses0603/WLRe_lala/actions/runs/42417788272)
are both green. Windows, macOS and Linux each pass **40,575 Core tests**, **59 lifecycle
tests** and **9 Desktop self-tests**, with Desktop builds reporting zero warnings/errors;
the Android validation APK job passes. These remote receipts exclude the newer
optional-portal and supplied-database-matcher increments.

The macOS diagnostic step reports SQLite **3.49.1**. A configured **250-ms** busy
budget took approximately **0.786–0.956 seconds** of elapsed time, and a requested
**1-ms** `sqlite3_sleep` took approximately **10 ms**, not a whole-second fallback.
These observations and the successful newer Python run do not establish a unique
cause or fix for the two earlier 8.0.17 timing failures. Existing assertions and
production behavior remain unchanged.

### Integrated verification for published commit `22c569a` (8.0.19)

The tree including `6e44908`, `7d04773` and `3445831`, published as `22c569a`, passes **40,832 Core Release
tests**, with **zero failures/skips** and **zero build warnings/errors**, under the
process-only `DOTNET_GCHeapHardLimit=0xC0000000` (**3 GiB**). This is a local capped
aggregate, not a standard-setting local pass or a new remote CI result. The published
**40,575** receipt excludes these increments; focused/impacted counts remain separate.

Final local checks pass **59/59 lifecycle tests**, Desktop Release with **zero
warnings/errors** and **9 offline self-tests**. The retained Python suite runs
**2,273 tests** with **216 existing skips**; strict repository audit passes with
**293 checked links**. Repository GC policy, Python timing assertions and production
SQLite behavior remain unchanged. The published remote receipts follow below.

Candidate event-only observations and supplied database matches remain separate from
official provenance, real transaction coherence, admission or runtime installation.
Optional portal sources remain unavailable through the owned candidate flow, and
actual-game/device/live acceptance is not established. `IsCompleteState` remains false.

Published `22c569a` [.NET CI run 42419400476](https://github.com/blesses0603/WLRe_lala/actions/runs/42419400476)
and [Python CI run 42419400467](https://github.com/blesses0603/WLRe_lala/actions/runs/42419400467)
are both green. Windows, macOS and Linux each pass **40,832 Core tests**, **59 lifecycle
tests** and **9 Desktop self-tests**; the Android validation APK job passes. These
published-commit receipts exclude the newer `850b7af` handshake and `6d61601` HTTP
slices and the later read-only database reader. They do not change the capped settings
of the local aggregate, resolve historical SQLite timing failures or establish live/resource/runtime acceptance.


### Integrated handshake/HTTP/database-reader verification for published `a08c719` (8.0.20)

The integrated tree through `3848459`, published as `a08c719`, includes `850b7af`
and `6d61601` and passes **41,090
Core Release tests**, with **zero failures/skips** and **zero build warnings/errors**,
under the process-only `DOTNET_GCHeapHardLimit=0xC0000000` (**3 GiB**). This is a local
capped aggregate, not a standard-setting local pass or a new remote CI result. Both
handshake and database-reader embedded fixture resource entries were preserved during
integration. Repository/CI GC and test execution policies remain unchanged.

The retained Python suite runs **2,273 tests** with **216 existing skips**, and strict
repository audit passes with **297 checked links**. Final lifecycle **59/59**, Desktop
Release **zero warnings/errors** and **9 offline self-tests** also pass. The published
8.0.19 results above exclude this combined slice. Published `a08c719`
[.NET CI run 42421049909](https://github.com/blesses0603/WLRe_lala/actions/runs/42421049909)
and [Python CI run 42421049923](https://github.com/blesses0603/WLRe_lala/actions/runs/42421049923)
are both green. These receipts apply only to published 8.0.20 and exclude the subsequent
local increments above; 8.0.21 requires its own new CI verification.

The scripted handshake, uninstalled HTTP adapter and caller-configured read-only
transaction reader remain separate from production account transport, trusted source
provenance, resource admission and runtime installation. The resolved reader provider
regression does not fix or change the historical Python SQLite timing threshold.
Android/device/live acceptance remains open; `IsCompleteState` remains false.

### Read-only resource-owner increment (8.0.21)

Local `cafdfb8` adds internal `ResourceRuntimeOwner` after the separately evidenced
`a92e68b`, `d529af0`, `6cebec4` and `3b68ac7` slices. Its production factory owns the
default constrained HTTPS source and a concrete read-only/private-cache/non-pooled
SQLite connection. It accepts no caller-supplied source, provider, candidate or digest
map on that route. Construction performs no HTTP/database I/O. Refresh decodes owned
sources, compares real inventory blobs using internally derived hashes in one read
transaction, waits for cleanup and rechecks versions and both complete manifests.
Exact dynamic DataVer, ExeVer and complete package identities are required; no shipped
1275/executable equality gate is silently added.

Only a production-created, non-disposed owner can admit its exact current publication
reference at its current generation. Invalidated, stale or fabricated publications
cannot admit; `TlsOriginObserved` follows the same current-owner check. This uses normal
OS TLS trust, not publisher signatures or proof of protocol compatibility. Offline-test
publications always remain non-authorizing, and existing decoder/preparation flags stay
false. The owner is **implemented but uninstalled and unpublished**, with no bootstrap,
database writes, disk bundle-cache reuse, runtime-global installation, login/lifecycle
registration, packet sending or Android activation. A missing inventory fails closed.
Lexical path normalization is not hostile-filesystem/symlink protection.

Refreshes are single-flight through real retirement. Invalidation/disposal revoke Current
synchronously; cancellation callbacks run outside locks and all admitted work is joined.
Self-reentrant disposal requests cleanup but fails its own join explicitly; external
callers share the true cleanup task. The documented context-loss/externally dispatched
dependency-cycle limitation remains, and arbitrary callbacks cannot be forced to return.
**24 focused tests passed in three runs**, with independent final review. They exercise
owned fixtures, real temporary SQLite, tampering, manifest replacement and adverse
retirement/reentrancy, not successful live HTTPS-origin acquisition. See
[resource-owner scope and limits](dotnet-resource-runtime-owner.md).

Core now pins Microsoft.Data.Sqlite **[10.0.14]**, bringing transitive SQLite/native
assets. Fresh Android CI packaging and native-load/device compatibility remain unverified;
the source change and historical Android build receipts do not settle those gates.
`2d7ba5b` only adds `AVALONIA_TELEMETRY_OPTOUT=1` and `DOTNET_CLI_TELEMETRY_OPTOUT=1`
to CI. It does not change tests, assertions, GC policy, compilation or acceptance criteria.

The initial combined Core run reported **41,500 total / 41,497 passed / 3 failed**:
two HTTP cleanup-race failures and one older provider-independent architecture assertion.
Those corrections are retained. Final combined validation now appears below; the historical
failed/intermediate runs are not treated as successful acceptance evidence.

### Owned inventory bootstrap and recovered 8.0.21 validation

The internal, uninstalled `BootstrapAndRefreshAsync` now composes actual ten-table extraction
with the existing bounded inventory writer, independent read-only snapshot and byte matcher,
then final versions/manifest reobservation. It creates the fixed inventory only after source
preparation succeeds. `RefreshAsync` remains read-only. The original native-extracted bytes,
not reserialized catalogs, are retained with the internally derived manifest identity.

Commit admission checks the owner generation, exact attempt, disposal and cancellation before
uncancelled COMMIT execution. Confirmed commits and uncertain outcomes remain distinguishable
from publication; later cancellation, readback/source drift or cleanup failure cannot pretend
a durable write rolled back. The owner remains occupied through writer and callback retirement.
No UI, AccountSession, Android adapter or real login uses this owner yet. Static 1275 pins,
optional resources, archive publication, global runtime installation and live/platform acceptance
remain separate. No login/packet authority is created. See the complete
[bootstrap contract and validation](../dotnet/Lala.Core.Tests/Resources/RuntimeFlow/BOOTSTRAP.md).

Final recovered cloud validation on 2026-11-08 UTC:

- **41,546 Core tests passed**, zero failures/skips, using the existing process-only 3 GiB
  heap limit. The preceding standard-settings run was aborted by a test-host crash, not a pass.
  No tests, assertions, parallelism or CI GC policy were relaxed.
- **59 lifecycle tests**, Desktop Release **zero warnings/errors**, **9 offline self-tests**.
- Python **2,273 total, 216 existing platform skips**, no failures; strict repository audit
  and all **six** repository-audit tests passed. Xvfb was unavailable; GUI acceptance is not claimed.
- Independent review found no blocking implementation issues. Added final-cleanup cancellation
  coverage confirms committed bytes and matched readback survive while publication is revoked.
- These are local results. Fresh standard-settings remote CI and Android APK/native packaging
  must still be checked against the exact published 8.0.21 commit. Prior APK/CI receipts do not
  cover the newly introduced SQLite native dependency. No live source, game credentials,
  user database, actual device or game-server acceptance is claimed. `IsCompleteState` stays false.

After preserving concurrent Desktop commits `906fd2e` and `97ab83e` unchanged, the combined
Desktop build again passed with zero warnings/errors, **9 inspector** and **54 presentation**
self-test checks. The first final-location Core rerun had **41,545 passed / 1 failed** in the
HTTP response-disposal test. Its independent review identified test-only LIFO callback
unregistration, corrected with explicit callback completion and an exactly-once assertion.
Production code and Desktop UI were not changed by that correction. After correction,
all **13 HTTP cleanup cases passed in four independent runs** (initial plus three bounded
repeats), and the final combined tree passed **41,546 Core / 59 lifecycle** again, with no
failures or skips. Full Core used the documented process-only 3 GiB cap; repeats are not
additional distinct test cases. Desktop's 9 + 54 self-tests and zero-warning/error build
remain applicable because production/UI code did not change. Standard remote CI remains
separate and must be verified against the pushed commit.


### Overall PR development marker 8.0.22: integrated account notifications

The user confirmed that the 8.x sequence belongs to the overall PR, not a separately
versioned Core package. Existing commit `d9ce54f` and the 8.0.21 entries above establish
the prior marker. The integrated-notification feature published as `493ba3e` advances
that overall marker once to 8.0.22; same-batch test, CI, documentation and push corrections
do not advance it again. No retrospective versions are invented for intervening commits.

The exact published feature passed 43,238 Core tests on Windows, macOS and Linux,
76 lifecycle cases, the public contract, 23 synthetic acceptance cases, Desktop build
and 9 + 54 offline checks; Android build and Python CI also passed.
This documentation alignment does not establish live-server or device acceptance.
Python 7.3.1 and Android 0.2.0 / versionCode 2 remain independent. Core and Desktop
project version settings are unchanged; no independent Core version is introduced.
See the root version history for the same-batch policy and current PR marker.


### Overall PR development marker 8.0.23: verified bundle cache population

Bootstrap now persists owned verified bundle bytes after inventory readback and before
final source revalidation. Refresh remains read-only. Per-file staging, integrity checks,
atomic publication, cancellation and cooperative-writer protections are bounded to 24 files
and 32 MiB per batch. Cache failure retains the truthful database storage outcome and
prevents publication. No cache entry grants source freshness or action authority.

Focused Resources/Sessions: 2,780 passed; full Core: 43,294 passed. Unix link cases are
platform-conditional, not proof of Windows reparse behavior. No hostile-filesystem,
multi-file rollback, power-loss durability, eviction or live-source acceptance is claimed.
See `dotnet-resource-bundle-cache.md` for the exact contract. This new feature advances
only the overall PR marker once; subsequent fixes retain 8.0.23. Platform versions and
Core/Desktop project version settings remain unchanged.


### Overall PR development marker 8.0.24: single-attempt login preparation

The opt-in preparation composition privately binds a fixed profile, opaque selected identity,
exact account snapshot and credential input. Both credential-bearing TCP write admissions
recheck lifetime, cancellation and account revocation. Already-admitted writes cannot be
recalled; noncooperative input keeps cleanup pending. No automatic retry or reacquisition.

Frozen Release verification: 41 focused / 43,324 full Core tests passed, including 30 new
synthetic cases; public consumer check passed and independent review found no blocker.
This is not authenticated human consent, a secure-input host, or live-server validation.
Existing direct runtime callers and integrated resource composition do not automatically
use this boundary. See `dotnet-account-login-preparation.md` for limits.
Only the overall PR marker advances to 8.0.24; platform/project versions are unchanged.
Same-batch test, CI, documentation or push corrections do not advance it again.


### Overall PR development marker 8.0.25: prepared acceptance integration

The acceptance runner now offers an explicit CreatePrepared route. Construction fixes
its private session, selected identity, profile and AccountLoginPreparation and exposes
the exact disclosure before Run. It uses the existing two credential-write guards;
construction-time validity is not restarted. Stop/disposal retain one-shot ownership
and join late input cleanup. Legacy raw-source/resource routes retain their distinct limits.

Synthetic acceptance: 36/36 (13 new); full Core: 43,324/43,324; lifecycle: 76/76;
public consumer passed. These are loopback checks, not trusted human permission, secure
input, safe raw-TCP transport or live-server validation. No resource download is implicit.
See the acceptance README for disclosure and lifecycle contracts. This new feature advances
only the overall PR marker once to 8.0.25; same-batch corrections retain it. Platform and
Core/Desktop project version settings remain unchanged.


### Overall PR development marker 8.0.26: interactive terminal synthetic acceptance

The terminal self-test now exercises real intercepted input through the prepared runner,
two fixed loopback peers, held receive, heartbeat and cleanup. Only the displayed fixed
fake pair is admitted; other input is cleared/rejected before transmission. There is no
arbitrary destination, live mode, Desktop UI change or user-machine deployment.

Frozen validation: 43,324 Core, 76 lifecycle, 36 acceptance and 17 actual Linux PTY
checks passed, plus the public consumer. Linux PTY coverage is added to CI. Windows/macOS
terminal behavior remains unverified. This is not authenticated consent or secure OS input;
startup echo, OS/runtime copies and forced-process-exit cleanup are outside guarantees.
Only the overall PR marker advances once to 8.0.26; same-batch corrections retain it.
Platform and Core/Desktop project version settings are unchanged.


### Overall PR development marker 8.0.27: interactive login role selection

Explicit opt-in role selection is wired through login preparation, connection runtime
and integrated AccountRuntime. Pre-Run disclosure distinguishes interactive selection
from the unchanged fixed-role default. Interactive mode permits one attempt only.
Immutable requests and opaque choices bind the exact server role list and handshake epoch;
late choices after cancellation/retirement cannot admit selection writes. Heartbeats continue
while a selector waits, and noncooperative callbacks remain owned until cleanup completes.

Final verification: 43,345 Core tests (21 new), public consumer, 36 acceptance and 76 lifecycle
checks passed. These are synthetic checks, not trusted consent, Desktop integration or live
server validation. No UI or gameplay command authority changed. Only the overall PR marker
advances once to 8.0.27; same-batch corrections and platform/project versions stay unchanged.


### Overall PR development marker 8.0.28: prepared integrated account lifetime

AccountRuntime.CreatePrepared joins the private single-attempt credential admission,
optional interactive role selection and existing long-lived receive/resource lifecycle on
one connection. Separate immutable login/resource disclosures identify recipients and
normalized inventory/cache paths before Run; they are not authenticated permission.
A captured revision and exact-snapshot owner reservation close retirement admission gaps;
deferred work checks epoch before I/O and retains cleanup ownership with one-shot execution.

Final frozen offline verification passed: 26 focused, 43,364 Core, external public consumer,
76 lifecycle, 36 acceptance and 17 actual Linux PTY checks. Successful catalog binding uses
white-box synthetic provenance, not official-source or live-account evidence. Actual-input
Desktop/Android hosts remain unconnected. Overall PR advances once to 8.0.28; same-batch
corrections and all platform/Core/Desktop version settings remain unchanged.


### Overall PR development marker 8.0.29: receive publication notifications

AccountRuntime now exposes a stable PublicationSnapshot and cancellable
WaitForPublicationChangeAsync for receive commits, catalog selection/revocation,
connection changes and aggregate cleanup completion. The existing lifecycle wait
remains independent of packet traffic. Asynchronous rotating signals and bounded
owned waits replace host polling without introducing a lossless event queue.
Exact attempt/generation joins remain mandatory; retained snapshots are historical,
read-only observations and never gameplay command authority.

Final offline verification passed: 12 focused, 43,384 Core, external public consumer,
76 lifecycle, 36 acceptance and 17 actual Linux PTY checks. Independent review found
no blockers. No Desktop UI, trusted-input host or live-server acceptance is implied.
Only the overall PR marker advances once to 8.0.29; same-batch corrections and all
platform/Core/Desktop project version settings remain unchanged.


### Overall PR development marker 8.0.30: bounded received chat state

Decoded chat is now composed into the actual service snapshot before its atomic
commit. The latest 200 full message/announcement receipts and 4096 scoped names,
plus latest feedback/profile observations, survive coalesced receive notifications.
New receive attempts start empty; scene and resource updates do not erase history.
Raw content remains explicitly accessible for literal host display while default
diagnostics are redacted. This adds no sending, link execution or command authority.
Python comparison and the deliberate deterministic name-order/profile-learning
completions are documented in dotnet-received-chat.md.

Final offline verification passed: 15 focused, 43,401 Core, external public consumer,
76 lifecycle, 36 acceptance and 17 Linux PTY checks. Independent review found no
blockers. No Desktop UI, real credentials or official-server acceptance was involved.
Only the overall PR marker advances once to 8.0.30; same-batch corrections and all
platform/Core/Desktop project version settings remain unchanged.


### Overall PR development marker 8.0.31: runtime battle receive context

The actual receive writer now stages full service reduction followed by the narrow
Python SessionLogic.receive battle overlay, committing canonical state and pending
context together. An announced S11-10 style survives the next S11-250 start and is
consumed once; the first qualifying own exit clears pending style and records inactive
battle state. Fresh attempts never import pending announcements from old snapshots.
Standalone service/battle reducer behavior stays unchanged. No post-battle timer,
event continuation, cooperative count consumption, scheduling or sending is added.

Final offline verification passed: 342 focused, 43,422 Core, external public consumer,
76 lifecycle, 36 acceptance and 17 Linux PTY checks. Thirteen actual Python receive
sequences produced 112 matching snapshots, and public loopback exercises reconnect.
Independent review found no blockers. No UI, real credentials or official-server
acceptance was involved. Only the overall PR marker advances once to 8.0.31;
same-batch corrections and platform/Core/Desktop versions remain unchanged.


### Overall PR development marker 8.0.32: cooperative fight bookkeeping

The receive-owned first-own-exit overlay now records style-16 cooperative fight
consumption after full service reduction. An independent battle marker prevents
repeated consumption across role changes. Counts and own-side victory preserve
Python's unknown and ambiguity rules, without introducing delay results, timers,
continuation, readiness or sending. Standalone instance observers remain unchanged.
Six Python delay-arithmetic failures outside this scope are explicitly documented;
this is not full SessionLogic scheduler parity.

Final offline verification passed: 1,305 focused, 43,473 Core, 86 Python regressions,
external public consumer, 76 lifecycle, 36 acceptance and 17 Linux PTY checks.
The 41-sequence / 302-snapshot Python oracle regenerates identically. Independent
review found no blockers. No UI, real credentials or live-server acceptance was
involved. Only the overall PR marker advances once to 8.0.32; same-batch corrections
and platform/Core/Desktop project versions remain unchanged.


### Overall PR development marker 8.0.33: read-only expedition task assessment

The assessment captures one exact account publication before calculating task duration,
conservative reward space, explicitly selected members and observed recovery stock.
Unknown or revoked evidence is not treated as zero or dispatch permission. Results
remain historical and held; no team selection, reservation, item use, dispatch, claim,
scheduler, packet or Desktop UI change is introduced.

This batch is being reimplemented from remote 85d7c3f after the original worktree
became inaccessible. Preserved blobs are reference artifacts, not proof that the
original commit was restored. Previous test results do not validate this reconstruction;
fresh Release verification passed 261 focused and 43,734 full Core tests, with no
failures or skips. The external public consumer and 35 release/version checks also
passed, followed by 76 lifecycle, 36 synthetic acceptance and 17 Linux PTY checks.
Independent source review found no blockers. These are offline checks, not native
Windows/macOS/Android device or official-server acceptance.
No real credentials or official-server acceptance is involved. The overall PR marker
advances to 8.0.33 once; reconstruction and same-batch repairs do not increment it
again, and platform/Core/Desktop project version settings remain unchanged.


### Overall PR development marker 8.0.34: battle rule candidate chooser

Port the actual Python AutoBattle.choose_action priority and target-selection rules
onto the existing pure action, skill and food candidate planners. Typed immutable
profiles are bounded, sparse evidence remains explicit, and only the source's
ProtocolError failures permit rule fallthrough. Results contain candidate intent and
reason or error, never send authority.

This increment does not install AutoBattle.tick, timers, reservations, settings
persistence, Desktop UI or AccountRuntime actor projection. Independent review found
no blockers. Fresh checks passed: 1,032 focused, 44,766 full Core, external public
consumer, 76 lifecycle, 36 synthetic acceptance, 17 Linux PTY and 35 release/version
checks. The 1,005 actual-Python vectors regenerate identically. No real credentials,
game commands or official-server acceptance are involved. Only the overall PR marker advances once
to 8.0.34; same-batch repairs and platform/Core/Desktop project versions are unchanged.


### Overall PR development marker 8.0.35: crafting material preflight

A bounded immutable preflight calculates explicit recipe/tool selection and ordered
bag-first/material-cupboard allocations from supplied observations. It preserves the
supported Python helper's gates and error order without building a packet, acquiring
holds, enqueueing work, confirming consumption or enabling continuation. Existing
pending/unknown observations remain evidence, not permission or verified ownership.

The immutable catalog contract and typed-input bounds are documented separately from
source-helper parity; packet construction and changing global catalog identity are
outside this calculation. Fresh verification passed: 160 focused, 44,926 full Core,
external public consumer, 76 lifecycle, 36 synthetic acceptance, 17 Linux PTY and
35 release/version checks. The 154 actual-Python prefix vectors regenerate identically;
independent review found no blockers. No Desktop UI, real credentials or official-server acceptance
are involved. Only the overall PR marker advances once to 8.0.35; same-batch repairs
and platform/Core/Desktop project versions remain unchanged.


### Overall PR development marker 8.0.36: logical-map route preview

Compose existing mesh routing with explicit logical-map stages, origin and height
conversion, fixed compatibility pins, house-navigation exclusions and scene-scoped
stale checks. Inputs are bounded immutable supplied observations; caller-claimed
identity is not official provenance, current runtime freshness or movement authority.

No cache downloading/import, dynamic obstacle rebuilding, UI, transport or movement
is added. Synthetic alias tests must not weaken public fixed-order checks; a genuine
reviewed-order positive fixture remains unavailable. Fresh checks passed: 67 focused,
44,993 full Core, public consumer, 24 Python navigation regressions, 76 lifecycle,
36 synthetic acceptance, 17 Linux PTY and 35 release/version checks. The 47 actual
Python oracle cases regenerate identically; independent review found no blockers.
No real credentials or official
server acceptance are involved. Only the overall PR marker advances once to 8.0.36;
same-batch repairs and platform/Core/Desktop project versions remain unchanged.


### Overall PR development marker 8.0.37: received battle actor integration

BattleUnitState.Actor and ordered BattleEventSnapshot.Actors now derive directly
from committed receive state, without a second store or new inspection endpoint.
Current HP/SP and appearance preserve received overrides; maxima remain original
layout values, separate from owned profile knowledge. Missing fly/status evidence
is not inferred. Replacements and retained historical snapshots preserve boundaries.

Focused/Python transition parity 25, full Core 44,998, the existing public consumer,
and an isolated external consumer of the new APIs passed; independent review found
no blockers. The framed chooser compatibility case uses explicitly synthetic catalogs,
not a production combat pipeline. Complete combat/normal catalog constants and chooser
scheduling remain unfinished. No live credentials, official server, UI or sends were
used. Overall PR advances once to 8.0.37; same-batch fixes and platform/Core/Desktop
project versions remain unchanged.


### Overall PR development marker 8.0.38: runtime crafting material join

AccountRuntime.InspectCraftingMaterials captures one exact publication and evaluates
its joined recipe catalog, known role, furniture/schedule, bag and room storage
outside the runtime lock. Missing publication/catalog/identity yields explicit
unavailable outcomes, without cached fallback. Pending/uncertain observations and
old results remain historical; material sufficiency never grants command authority.

Focused 165, full Core 45,003 and the public consumer passed; independent review
found no blockers. Framed runtime fixtures demonstrate closed-product results,
source identity, retirement, resource revocation and reconnect. Successful material
allocation is separately covered by explicitly synthetic projection, not a received
open official recipe. No commands, UI, credentials or official server acceptance
are added. Overall PR advances once to 8.0.38; same-batch repairs and platform/Core/
Desktop project versions remain unchanged.


### Overall PR development marker 8.0.39: runtime maintenance knowledge

Port source maintenance repair-target ordering, equipment lookup, backpack repair
stock, configured supply selection and cleanup restriction classification. The
runtime captures one exact publication before evaluating reviewed item metadata
and received equipment/bag observations outside the gate. Sparse durability,
reservation exclusions, active-companion ordering and historical state remain
explicit. Catalog binding alone does not resolve equipment before the next receive.

78 actual-Python oracle cases regenerate identically. Focused 83, full Core 45,086
and public consumer passed; independent review found no blockers. Positive metadata
cases use explicit synthetic reviewed rows, while framed held fixtures test joins
and lifecycle rather than official provenance. No repair/sell/delete packets,
reservation changes, scheduler, UI or real-server acceptance are added. Overall PR
advances once to 8.0.39; same-batch fixes and platform/Core/Desktop versions do not.


### Overall PR development marker 8.0.40: required-source normal attack catalog

Compose the public reviewed normal-attack builder with owned required NPC/item
bytes during runtime decoding. Normal attacks require no Lua. Nullable catalog
availability follows existing candidate copies, exact required-source SQLite
readback, source recheck and account revocation, without additional downloads.
Unknown reviewed pins leave this optional feature unavailable; no gate is relaxed.

Focused 1,072, final wiring 5, full Core 45,089 and public consumer passed;
independent review found no blockers. Structural IL coverage proves the decoder
calls the public pinned builder. Synthetic positive copies/rule consumption do
not establish a successful reviewed raw-payload pair; that acceptance remains
unavailable. Full Lua combat acquisition/persistence and command lifecycles remain
unfinished. No UI, credential or official-server changes. Overall PR advances once
to 8.0.40; same-batch fixes and platform/Core/Desktop versions remain unchanged.


### Overall PR development marker 8.0.41: desktop login and role host

Avalonia now supplies transient user input, per-recipient credential-write confirmation,
interactive role choice and awaited shutdown to the shared single-attempt preparation.
Explicit IP endpoints and decimal protocol bytes have no production defaults. Both raw
TCP recipients disclose reversible XOR / no TLS before their credential write. The host
never stores credentials or enables game commands; publications remain resource-held.

Validation: Core 45,096; focused login 78; public consumer; desktop offline 63;
Linux native UI 142 and synthetic loopback login 11 assertions, 16 rendered screenshots.
No real credentials, production connection or user-computer operation. Windows/macOS
live UI and official-server acceptance remain outstanding. Overall PR marker moves from
8.0.40 to 8.0.41 once; platform/Core/Desktop versions remain unchanged. See
[desktop login integration](DESKTOP_LOGIN_INTEGRATION.md).

### Overall PR development marker 8.0.42: Python desktop parity inventory

Replaced technical login fields with official server/line selection and release-owned
Python protocol settings. Unknown/failing/stale metadata blocks login. Added primary
feature windows and a complete source/geometry/gap inventory; resource activation,
several projections, local editors and child dialogs remain incomplete. This is not
full Python UI parity or live acceptance. See [the inventory](DESKTOP_PYTHON_PARITY.md).
The overall marker advances once; platform versions remain unchanged.

### Overall PR development marker 8.0.43: startup version and read-only resources

The dedicated Python-style startup window displays actual official version/package metadata
and invokes Core's read-only resource inventory inspector on an explicitly selected local root.
Login/dashboard navigation shares this window. Failures, stale metadata, cancellation and
local consistency cannot admit resources or game commands. Full resource activation,
background observation and application updates remain incomplete. See the parity inventory.
Platform versions remain unchanged; no live login or real credentials were used.

### Overall PR development marker 8.0.44: integrated desktop resource preparation

Opted-in desktop logins now use AccountRuntime.CreatePrepared with separate resource write
consent and per-recipient credential confirmation. The existing Core pipeline performs official
acquisition, SQLite readback/source recheck and account-scoped read-only catalog binding.
Desktop names follow the same publication and revoke with it. Commands remain Held; no
production resources or game servers were contacted during validation. See
[the integration record](DESKTOP_RESOURCE_INTEGRATION.md) for synthetic proof and limitations.

### Overall PR development marker 8.0.45: prelogin required resources

The account-free PreloginResourcePreparation facade reuses the private production resource owner.
Desktop explicitly confirms prelogin download/writes, waits for required table bootstrap/readback/source
recheck, then compares a fresh catalog's exact exe/data/package identity. Metadata alone cannot open
login; refresh/stop revokes admission and drains work. Account preparation independently rechecks later.
No packet authority is added. Sprite/Texture2D decoding, image database validation and visual publication
remain missing; HasVisualAssets is false. See DESKTOP_RESOURCE_INTEGRATION.md for Python dependencies.
Validation is synthetic/loopback only, with an explicitly labelled white-box positive identity seam.
Platform versions stay unchanged; overall draft PR marker advances once, without release or merge.
