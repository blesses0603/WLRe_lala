# LaLa C#/.NET + Avalonia migration

**Work in progress. This is not a replacement game client.** The Python app remains unchanged and usable. This first increment deliberately has no socket transport, login, server-command transmission or persistent credentials.

## Projects

- `Lala.Core`: platform-independent protocol, session safety, battle rule ports; no Avalonia or Android references.
- `Lala.Desktop`: Windows/macOS Avalonia host. Currently exposes a working **offline** frame inspector using the actual shared codec.
- `Lala.Android`: Android Avalonia host with a service-owned connection lifecycle, explicit notification permission/stop flows and the shared offline inspector. The actual Core login/transport adapter is still unavailable; no game connection is simulated. See [Android lifecycle and acceptance](Lala.Android/README.md).
- `Lala.Core.Tests` and `Lala.Android.Lifecycle.Tests`: tests only, not additional product projects.

The full source-by-source migration inventory is [migration-inventory.json](migration-inventory.json). Architecture, platform contracts and acceptance gates: [migration plan](../docs/DOTNET_MIGRATION.md). Not-yet-migrated features must not be enabled by substituting guessed protocol behavior.

## Build and verify

Install the official .NET 10 SDK. `global.json` allows newer .NET 10 feature bands. NuGet packages are pinned in the projects.

```sh
cd dotnet
dotnet test Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
dotnet test Lala.Android.Lifecycle.Tests/Lala.Android.Lifecycle.Tests.csproj -c Release
dotnet build Lala.Desktop/Lala.Desktop.csproj -c Release
dotnet run --project Lala.Desktop -c Release -- --self-test
dotnet run --project Lala.Desktop -c Release
```

`Lala.sln` includes core, tests and desktop so it builds without an Android workload. Android is built explicitly:

```sh
dotnet workload install android
dotnet build Lala.Android/Lala.Android.csproj -c Debug -p:EmbedAssembliesIntoApk=true
```

Android also requires a supported Android SDK and Java SDK. A successful cross-platform build is not a physical-device test, macOS signing/notarization, release-ready APK, or official-server acceptance.

## Offline verification boundaries

- Python-generated golden vectors verify exact packet bytes, fragmentation, Unicode and range rejection. Synthetic credentials are test data only.
- Resource safety holds are latched across a session generation. This is only a resource gate, not authentication or command authorization. Initial resource confirmation is not a background version monitor: subsequent mismatch detection must call `Hold`. This foundation does not implement the entire original service scheduler or connection state machine.
- Normal attack selection accepts explicit catalog snapshots. This does not yet load official Unity resources, send attacks or replace automatic battle.
- Inspector input is kept in memory only, headers/lengths are shown without payload. Do not enter real login captures. Cancel/close/background prevents late results from updating the display.

The independent branch and Draft PR remain open until all module parity, real platforms and official-server acceptance gates pass. No Python module is deleted in this initial increment.

The inventory index uses schema version 2: load the relative `module_files` to obtain all 696 entries. Partitioning keeps individual review/upload units small; no source entries were removed.

## Shared-core continuation

Activity decoding and movement-lock state now have an offline typed implementation, with 200 synthetic Python parity vectors and 28 edge-case tests. The complete Core suite at this increment contains 1180 passing tests. This does not connect activities to a live session or movement dispatcher. Subsequent work prioritizes Core parity; no expansion of the desktop or Android interface is included in this increment.

The next Core increment adds offline ItemData/SkillData parsing and stack rules; single-writer scoped state ownership; role/world/battle/social layouts; S31 expedition events; and geometry-only navigation/funnel/motion checks. The integrated Release suite contains **2607 passing tests**. Independent review and retained Python vectors cover bounded source subsets, not full functional migration. Catalog activation, real session/dispatcher integration, runtime movement and official-resource/device/server acceptance remain incomplete. See each test area's README/LAYOUTS.md/EXPEDITION.md and inventory scope entries.

The following Core increment adds the typed server dispatcher, all live-data layouts, receive-only chat/guild/instance decoding, immutable session event reduction, completed-battle EXP efficiency, and bounded/cancellable resource identity metadata validation. **8201 Release tests pass** after integration. Chat/guild/instance results now flow through the dispatcher; unported service families remain explicitly unsupported. Session event reduction does not modify AccountSession or transport lifecycle. Resource observations remain non-authorizing and do not activate catalogs.

## Android lifecycle increment (v0.2.0 candidate)

The subsequent Android increment prepares foreground service ownership, reconnection/cancellation guards and platform status UI while Core continues independently. It does not modify Core APIs or implement its missing transport. The default adapter reports unavailable, process death never silently restores login, and all live-server/device acceptance remains separate. Desktop's Python version remains 7.3.1; Android C# host versions are independent.

### Public host composition

Core now exposes explicit, inert `AccountConnectionRuntime` and
`AccountResourceRuntime` boundaries. See
[connection ownership and limits](../docs/dotnet-account-connection-runtime.md) and
[resource preparation](../docs/dotnet-account-resource-runtime.md).
The no-friend-assembly consumer smoke check is:
`dotnet run --project dotnet/Lala.Core.PublicContract.Check -c Release`.
This does not activate host UI wiring, command sending, or live-server validation.

`AccountRuntime` now joins connection and resource lifetimes: login first, one
bootstrap, read-only refresh after reconnect, and current catalog observations in
the held receive pipeline. See [ordering and validation limits](../docs/dotnet-integrated-account-runtime.md).
