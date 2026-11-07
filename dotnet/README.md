# LaLa C#/.NET + Avalonia migration

**Work in progress. This is not a replacement game client.** The Python app remains unchanged and usable. This first increment deliberately has no socket transport, login, server-command transmission or persistent credentials.

## Projects

- `Lala.Core`: platform-independent protocol, session safety, battle rule ports; no Avalonia or Android references.
- `Lala.Desktop`: Windows/macOS Avalonia host. Currently exposes a working **offline** frame inspector using the actual shared codec.
- `Lala.Android`: Android Avalonia host linking the same presentation sources, with cancellation on backgrounding. Production foreground connection, secure storage, notifications and permission flows are not implemented yet.
- `Lala.Core.Tests`: tests only, not a fourth product project.

The full source-by-source migration inventory is [migration-inventory.json](migration-inventory.json). Architecture, platform contracts and acceptance gates: [migration plan](../docs/DOTNET_MIGRATION.md). Not-yet-migrated features must not be enabled by substituting guessed protocol behavior.

## Build and verify

Install the official .NET 10 SDK. `global.json` allows newer .NET 10 feature bands. NuGet packages are pinned in the projects.

```sh
cd dotnet
dotnet test Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
dotnet build Lala.Desktop/Lala.Desktop.csproj -c Release
dotnet run --project Lala.Desktop -c Release -- --self-test
dotnet run --project Lala.Desktop -c Release
```

`Lala.sln` includes core, tests and desktop so it builds without an Android workload. Android is built explicitly:

```sh
dotnet workload install android
dotnet build Lala.Android/Lala.Android.csproj -c Debug
```

Android also requires a supported Android SDK and Java SDK. A successful cross-platform build is not a physical-device test, macOS signing/notarization, release-ready APK, or official-server acceptance.

## Offline verification boundaries

- Python-generated golden vectors verify exact packet bytes, fragmentation, Unicode and range rejection. Synthetic credentials are test data only.
- Resource safety holds are latched across a session generation. This is only a resource gate, not authentication or command authorization. Initial resource confirmation is not a background version monitor: subsequent mismatch detection must call `Hold`. This foundation does not implement the entire original service scheduler or connection state machine.
- Normal attack selection accepts explicit catalog snapshots. This does not yet load official Unity resources, send attacks or replace automatic battle.
- Inspector input is kept in memory only, headers/lengths are shown without payload. Do not enter real login captures. Cancel/close/background prevents late results from updating the display.

The independent branch and Draft PR remain open until all module parity, real platforms and official-server acceptance gates pass. No Python module is deleted in this initial increment.

The inventory index uses schema version 2: load the relative `module_files` to obtain all 696 entries. Partitioning keeps individual review/upload units small; no source entries were removed.
