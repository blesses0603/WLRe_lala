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

Latest combined local core test run: **952 passed, 0 failed, 0 skipped**. This count includes synthetic parity and boundary cases, not 952 end-to-end game features.

The inventory index uses schema version 2: load the relative `module_files` to obtain all 696 entries. Partitioning keeps individual review/upload units small; no source entries were removed.
