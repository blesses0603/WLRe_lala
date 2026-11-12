# Offline daily-task catalog parsing and binding

This bounded slice ports the pure parts of:

- `wlre/services/world/daily_task_1275.py`: `Reader`'s little-endian widths and strict truncation, `parse_daily_tasks` group/task counts, cycle and scoped-index uniqueness, all raw fields, sorted missing-group observations, and trailing-byte rejection.
- `wlre/services/world/daily_task_catalog.py`: `parse_rewards` counts, kind/id/mark/value checks, all four awards, `goal` branches, and `bind_catalog` daily/weekly selection, global indices, per-group slots, name lookup, and kind 10/11 item-reference checks.

`DailyTaskDataParser` returns immutable task/group and reward tables. `DailyTaskCatalogBinder.Bind` returns an immutable `DailyTaskCatalogPreview`, including names and every original field. Text and item inputs must be stable snapshots. Names are preserved without trimming; the Python whitespace-only rejection includes ASCII separators U+001C–U+001F. The typed text dictionary cannot contain the Python binder's non-string values; null, missing, and blank values are rejected.

Parsing deliberately does **not** reject a missing task group, zero task index, unknown condition/award/function kind, or empty task table when Python accepts it. Binding rejects missing groups before skipping non-daily mission kinds, rejects empty daily/weekly results, and enforces the source's stricter selected-task metadata and slot rules. Unknown goals stay null; zero goals and unrecognized award kinds remain uninterpreted, rather than inventing progress or reward semantics. `uint32` values and item identifiers are never narrowed. A reward mark is narrowed only after the parser validates 1–8.

## Authority and integration boundary

This is syntax and reference consistency, not official-resource verification. The preview always reports `AssetsReady == false` and `CanSendPackets == false`. It does not mint an identity token or construct `DailyCatalogInput`. `ToPlanningDefinitions()` projects only the fields the existing offline planner consumes, preserving all widths and award order. The preview still retains reward IDs, names, and other fields omitted from planner definitions.

A future verified activation layer must independently validate the exact source bytes and the identity of task/reward/text/item snapshots before constructing `DailyCatalogInput`. No actual resource extraction, manifest or SQLite loading, hashing-based source approval, runtime activation, account/session/lifecycle wiring, socket I/O, transmission, UI, or Android behavior is included. In particular, `load_verified_catalog` is not ported, and no provided identity or metadata claim is treated as verified runtime authority.

## Verification

```sh
python dotnet/Lala.Core.Tests/Catalogs/generate_daily_catalog_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~DailyTaskCatalogTests
```

The deterministic generator imports and runs the retained Python functions, using synthetic bytes and metadata only. It emits 115 task-layout vectors, 74 reward-layout vectors, 144 binding vectors, and 1,029 goal vectors. Expected results come from Python, not a duplicated C# expectation. Tests compare every returned field, including unsupported fields, missing-group ordering, all four reward awards, preserved names, and all planning-projection fields. Coverage includes every prefix truncation of a valid task/reward table, count bounds, trailing bytes, unsigned extremes, duplicates, all condition-kind bytes and kind-13 subtypes, missing/blank names, missing item references, and skipped non-daily rows.

Additional C# tests exercise 50,000 task rows, all 256 group identifiers, impossible unique group/reward count boundaries, oversized/default spans, cancellation, null typed metadata, and mutation isolation. These tests prove offline source parity and bounded validation only, not live-server, real-resource, desktop, or Android acceptance.
