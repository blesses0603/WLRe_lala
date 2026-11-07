# Android migration host (offline only)

The launcher uses Avalonia.Android 12.1.5 and the exact shared C# protocol inspector
source used by Desktop. It references Lala.Core, not the Python application.
The activity cancels pending inspection when stopped; no session is restored
implicitly after process death. Input is memory-only and is not saved to disk.

This is **not** a replacement for the existing Android application. The game
foreground service, persistent notification, notification runtime permission,
overlay permission, secure credential storage, battery/background policy and
reconnection behavior are **not migrated or enabled**. Accordingly this offline
manifest does not request network, notification, foreground-service or overlay
permissions. No dummy service pretends to maintain a game session.

Next acceptance gates: implement a user-started connection service with a visible
notification and explicit stop; deny/defer on rejected notification or service
permissions; test screen lock, process death, rotation, network switch and logout.
Do not auto-start a game session on boot or after the app is backgrounded.

Build with .NET 10 Android workload, Android API 36 SDK and supported JDK:

    dotnet build dotnet/Lala.Android/Lala.Android.csproj

A successful desktop build does not validate Android packaging, lifecycle, or a
physical device. See the migration inventory for the current acceptance status.

## Initial local validation result

.NET Android workload 36.1.2 installation and NuGet restore succeeded. Local build
stopped at XA5300 because the executor has no Android SDK; its Java 21 location
also lacks the JDK `jar` utility. Thus Android compilation/APK creation is **not
verified locally**. Native CI must provide a complete JDK 21 and Android API 36
SDK and build this project; do not infer success from Desktop or restore alone.
