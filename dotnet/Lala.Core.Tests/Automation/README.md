# Offline task-service parity

This slice ports the **offline** time-cube and daily/weekly reward lifecycle. It has no transport, UI, account login, resource downloads, condition execution, automatic challenge, or sweep feature.

## Source contracts

- `wlre/services/time_cube.py`: defaults; exact S122-1/2/3 decoding; role/list reset; server-only cube counts; countdown metadata; open/auto requests; pending count + newer reliable bag confirmation; 15-second uncertainty; disconnect.
- `wlre/services/daily_tasks.py`: defaults; exact S124-1/2/3/5 and reward-notice layouts; task/group generations and reset handshakes; one-indexed little-endian marks; eligibility, candidate order and batching; safe award/slot accounting; explicit task/chest/claim-ready requests; handled fingerprints; 20-second uncertainty; role/catalog changes; matching marks + notice kind + exact positive item deltas; auto stop and disconnect.
- `wlre/services/coordination.py`: the `time_cube` / `daily_tasks` branches of `reason`, `active`, and each service's bag-operation guard. These are observations, not a port of unrelated scheduling logic.
- `wlre/services/instance_rewards.py:bag_claim_problem`: conservative bag-ready/reliable/capacity/unique slot checks and reservations. Individual hold collections are collapsed into explicit `HasHolds` / `HasReservedItems` observations. `SupplyActive` includes uncertain supply; `Bag.SupplyPending` also participates directly.
- `wlre/network/commands.py`: cube manual-open world-acknowledgement gate; daily command acknowledgement is in its service.
- `wlre/network/service_scheduler.py`: pending-only settlement/timeout under a resource hold. `wlre/network/resource_safety.py:command_allowed` permits local auto-disable, but not enable/claim, during a hold.
- `wlre/services/world/daily_task_catalog.py`: input widths, valid slots/marks, duplicate catalog rejection. Full catalog extraction/binding is **not** ported by this slice.

## API and integration boundary

`TimeCubeProtocol.Decode(Packet)` and `DailyTaskProtocol.Decode(Packet)` return immutable typed events, null for an unsupported route, and `ProtocolException` for malformed supported layouts. S122-2 is always opaque and never a success receipt. Unknown S124-3 updates invalidate task readiness. Unknown reward-notice kinds remain opaque as in Python; they cannot complete a pending request.

`TimeCubeService` and `DailyTaskService` are pure reducers/planners over immutable records and `System.Collections.Immutable` collections. `RequestOpen`, `Request`, and `Tick` return `AutomationPlan<T>` with a replacement state and, at most, one **candidate** packet. No packet is sent and no reward is optimistically credited. Stopping automatic continuation retains pending evidence; it does not cancel an outstanding server request. Disconnect retains uncertainty. Duplicate, late, partial, or unrelated observations cannot authorize retries after an uncertain outcome.

A single owner must atomically retain each returned state and coordinate candidates. Discarding the returned state and planning repeatedly from the same old snapshot is not supported as a sending workflow. Session generation/account routing, the shared `OwnedState` adapter, live-session event activation, transport admission, and actual receipt of candidate commands are future integration work. These pure functions do not latch a mutable session-wide hold themselves: callers must preserve the existing `AccountSession` / resource-hold latch and provide its current observation on every operation. `AutomationContext.ResourceHeld` defaults to true. World confirmation, readiness and all relevant coordination observations are explicit inputs, never inferred from a timer.

`DailyCatalogInput` accepts an already verified same-runtime catalog and its immutable opaque identity token; it performs no file loading, resource verification, or identity activation. Missing identity, duplicate/invalid definitions, unsupported/random awards, invalid item IDs, and malformed/duplicate typed bag entries fail closed. The typed boundary additionally rejects non-finite clocks and duplicate bag slots before counting reward deltas (Python bags are dictionaries). These are input-domain safety checks, not invented protocol behavior. A uint32 chest threshold is retained even though current server activity values are uint8.

The compact `TaskMarks.WeeklyDone` ushort represents Python's two-byte little-endian marks; defaults use zero while unknown readiness/values remain explicit. Immutable rows retain eligibility/progress/received and their input definitions, but UI names, condition descriptions and execution-label strings are intentionally not duplicated here. No timer invents progress, a reset, or a claimable reward. `LastNotice` preserves the currently unused source default.

## Verification

Run:

```sh
python dotnet/Lala.Core.Tests/Automation/generate_automation_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~Automation
```

The retained Python modules generate 233 packet vectors and 74 sequences with 669 intermediate state comparisons. The generator uses only synthetic packets/catalogs and a local clock; it does not open sockets or load official resources. Holds are evaluated using the real `command_allowed` policy plus the scheduler's pending-only boundary. State comparisons include exact status, readiness/generation, pending receipts, bag baselines, eligible rows, handled-count suppression and candidate bytes. Handled fingerprint identities are exercised through repeated request rejection and generation/catalog transitions.

Additional tests cover immutable snapshots, fail-closed default resource admission, manual acknowledgement, stop-versus-disconnect semantics, cross-service uncertainty, wide award/threshold arithmetic, malformed typed inputs, default marks, catalog identity/uniqueness, and fabricated duplicate-slot reward receipts. These are offline tests, not live server, desktop, Android, or official-resource acceptance.

The common `ServerProtocol` dispatcher now wraps both receive families; all 233
packet vectors also pass through this integration. This does not activate the
pure reducers or candidate planners in a live session.
