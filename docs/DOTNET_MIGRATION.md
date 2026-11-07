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
| `wlre/network/protocol.py` → `CandidateCommands.cs` | `partially_migrated`: login/select-role/walk/attack/skill/item **byte builders** only; synthetic Python-generated vectors. | Live login/transport, server event decoding and full command dispatch are not implemented by this subset. A builder is not permission or readiness to send. |
| `wlre/network/resource_safety.py` → `ResourceSafetyPolicy.cs` | `partially_migrated`: `AllowsDuringHold` policy only. | Remaining routing and full resource/version lifecycle integration. |
| `wlre/services/battle/combat.py` → `CombatRules.cs` | `partially_migrated`: `normal_skill` and `effect_text`, with 450 passing offline tests (160 normal-attack vectors, 288 effect vectors, snapshot ownership and culture). | `unit_label`, `attack_lines`, live catalog loading and complete auto-battle are not ported by this subset. |
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

1. **UnityPy 1.25.4 / UnityFS**: desktop `requirements-extractor.txt` and `wlre/services/world/unity_textasset.py`, `navigation_sync.py`, `auto_catalog.py`, `portrait_assets.py`, `item_image_database.py`, `emoji_database.py`. Select and validate a .NET-compatible bundle/TextAsset implementation with actual reviewed samples, decompression limits, hashes, corrupted input and version changes. Until then this is a blocked capability, not a generic JSON substitute.
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
coalesced publication covers 23 operations. Service observers, actual account
lifecycle and live network routing remain unintegrated.

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
kinds. The omitted observer list is explicit; this is not complete State parity.

Separate bag/companion receive reducers preserve slot metadata/order, inventory
reliability, identity-sensitive reservation observations, unknown baselines,
companion append/reuse and buffered S8 attributes. Seventy-seven Python sequences
cover 1,616 snapshots. Player/battle knowledge, equipment/deferred updates,
learned-command helpers and full shared-session wiring remain outstanding.
These functions neither acquire reservations nor perform resource-consuming acts.

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
positions; transport and complete State remain outstanding.

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
No intent was persisted or accepted as a correct answer. Successful persistence,
candidate/solver completion and execution remain gaps. The post-local coordinator now
requires explicit runtime reads when source branches consume them; missing input is
not mislabeled as an observed unavailable runtime.

All eighteen State.apply observer positions now have bounded receive composition,
including shop, efficiency, guild actions and Ark after tent. Twenty-six additional
real-State.apply sequences cover 1,414 checkpoints and 38 event kinds. One atomic
publication owns every current projection; even a final Ark failure leaves the old
snapshot and packet count intact. IsCompleteState deliberately stays false: storage
completion, scheduler/commands, remaining State fields and transport are not inferred
from receiving packets, and these tests do not establish complete gameplay parity.

Inventory allocation now returns read-only candidates; reservation validation returns
a hypothetical immutable snapshot only after checking the entire batch. Slot ordering,
exclusions, duplicate aggregation, serial identity and source numeric quirks are
retained in 153 Python sequences / 2,032 snapshots. Neither a successful candidate
nor a proposed hold authorizes or installs a live resource acquisition.

Five combat-resource helpers now derive learned evidence, weapon groups, target
validity, healing effects and field context from explicit current mappings and known
snapshots. Companion skill insertion order is retained across overwrite/remove/re-add
and S15 replacement; imported ambiguous order is rejected rather than guessed. The
1,070 Python cases include 20 receive histories. Field equipment resolution returns
a replacement player snapshot; it does not secretly mutate prior publications or
infer health. Skill reasons/rows and action candidates remain separate work.

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
explicit safety differences. Reports cannot enable assets or commands. Filesystem
persistence, default paths and automatic parser instrumentation remain unimplemented.
