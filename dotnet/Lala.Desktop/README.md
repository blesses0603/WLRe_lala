# Avalonia desktop migration host

This is a working **offline diagnostic increment**, not the completed LaLa client.
It compiles against Lala.Core, validates hexadecimal frames with the same codec as
the C# parity tests, and shows only command headers and payload lengths. It does
not load Python, open sockets, store input, or authenticate game accounts.

Avalonia 12.1.5 is pinned; its official NuGet package includes a net10.0 target.
The same `Shared/` source is compiled into Lala.Android. Desktop-specific startup
and window lifetime remain here. Future game pages must use the core's commands
and state snapshots, never duplicate protocol or game rules in UI code.

## Build and run

    dotnet build dotnet/Lala.Desktop/Lala.Desktop.csproj
    dotnet run --project dotnet/Lala.Desktop -- --self-test
    dotnet run --project dotnet/Lala.Desktop

The self-test covers valid sample, whitespace, joined frames, invalid hex, empty
input, truncated frame, size limits and cancellation. It is not a native UI test.

Input is capped, decoding runs off the UI thread, repeated work is canceled,
late results cannot replace a newer request, and closing/detaching cancels work.
Only the first 100 packet headers are rendered. Payload contents are never shown.

## Current verification

- Linux .NET 10 build: passed, zero warnings/errors.
- Inspector self-test: nine checks passed.
- Isolated Xvfb 1024×768 launch: Chinese text and dark-blue layout inspected;
  loading the synthetic sample, decoding it and canceling were exercised.
- Native Windows/macOS startup, rendering, packaging and signing: not verified.
- Android native host and mobile touch/lifecycle acceptance: tracked separately.
- Login, inventory/skills, battle, maps and automation screens: not migrated here.
