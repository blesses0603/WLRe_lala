[CmdletBinding()]
param([switch]$Watch, [switch]$SoftwareEmulation)
$ErrorActionPreference = 'Stop'
$logDirectory = Join-Path $env:LOCALAPPDATA 'LaLa/AndroidPreview/Logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logPath = Join-Path $logDirectory ("preview-{0}-{1}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $PID)
Start-Transcript -LiteralPath $logPath | Out-Null
Write-Host "Startup log: $logPath"
. (Join-Path $PSScriptRoot 'AndroidPreview.Common.ps1')
$adb = Join-Path $AndroidPreviewSdk 'platform-tools/adb.exe'
$emulator = Join-Path $AndroidPreviewSdk 'emulator/emulator.exe'
foreach ($required in @($AndroidPreviewDotnet, $adb, $emulator)) {
    if (-not (Test-Path -LiteralPath $required)) { throw 'Preview tools are missing. Run setup_android_preview.bat first.' }
}
$avds = & $emulator -list-avds
if ($avds -notcontains $AndroidPreviewAvd) { throw 'LALA preview device is missing. Run setup_android_preview.bat first.' }
$serial = 'emulator-5580'
$devices = & $adb devices
if (-not ($devices -match "^$serial\s")) {
    $options = @('-avd', $AndroidPreviewAvd, '-port', '5580', '-no-boot-anim', '-no-snapshot-load', '-gpu', 'swiftshader')
    if ($SoftwareEmulation) { $options += @('-accel', 'off') }
    # A visible emulator window is the user-requested interactive preview surface.
    $emulatorOut = Join-Path $logDirectory ("emulator-{0}.stdout.log" -f $PID)
    $emulatorErr = Join-Path $logDirectory ("emulator-{0}.stderr.log" -f $PID)
    Start-Process -FilePath $emulator -ArgumentList $options -RedirectStandardOutput $emulatorOut -RedirectStandardError $emulatorErr | Out-Null
}
Write-Host 'Waiting for the Android preview emulator...'
$deadline = [DateTime]::UtcNow.AddMinutes(6)
do {
    if ([DateTime]::UtcNow -gt $deadline) { throw 'The emulator did not boot. Check emulator acceleration or retry with -SoftwareEmulation.' }
    Start-Sleep -Seconds 2
    # An existing emulator may still be offline during boot. Windows PowerShell
    # can treat native stderr as a terminating error under Stop, so only this
    # readiness probe tolerates it; deployment commands remain fail-fast.
    try { $ErrorActionPreference = 'Continue'; $booted = & $adb -s $serial shell getprop sys.boot_completed 2>$null }
    finally { $ErrorActionPreference = 'Stop' }
} until (($booted -join '').Trim() -eq '1')
$currentAvd = & $adb -s $serial emu avd name
if ($currentAvd -notcontains $AndroidPreviewAvd) { throw 'Preview emulator port 5580 belongs to another device; it will not be changed.' }
# Keep touch input available even when Android detects the host keyboard.
Invoke-AndroidPreviewCommand $adb -s $serial shell settings put secure show_ime_with_hard_keyboard 1
function Update-AndroidPreview {
    Write-Host 'Building and updating the emulator preview (Debug only)...'
    Push-Location $AndroidPreviewRepository
    try {
        & $AndroidPreviewDotnet build $AndroidPreviewProject -c Debug -f net10.0-android36.0 -r android-x64 -m:1 `
            "-p:AndroidSdkDirectory=$AndroidPreviewSdk" "-p:JavaSdkDirectory=$env:JAVA_HOME" -p:UseSharedCompilation=false
        if ($LASTEXITCODE -ne 0) {
            if (-not $Watch) { throw 'Android preview build failed.' }
            Write-Warning 'Build failed. The previous preview stays installed; fix the errors and save again.'; return
        }
        $artifacts = Join-Path $AndroidPreviewRepository 'dotnet/Lala.Android/bin/Debug/net10.0-android36.0/android-x64'
        $apk = Get-ChildItem -LiteralPath $artifacts -Filter '*-Signed.apk' | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        if (-not $apk) { throw 'The Debug preview APK was not produced.' }
        Invoke-AndroidPreviewCommand $adb -s $serial install -r $apk.FullName
        Invoke-AndroidPreviewCommand $adb -s $serial shell am force-stop io.lala.migration
        $resolved = & $adb -s $serial shell cmd package resolve-activity --brief io.lala.migration
        $activity = @($resolved | Where-Object { $_ -match '^io\.lala\.migration/[^\s]+$' })
        if ($activity.Count -ne 1) { throw 'The installed preview launcher activity could not be resolved.' }
        Invoke-AndroidPreviewCommand $adb -s $serial shell am start -W -n $activity[0]
        Write-Host 'LALA is running in official connection mode. Complete resource checks, then log in from the App. Interface demo is available separately.'
    }
    finally { Pop-Location }
}
Update-AndroidPreview
if ($Watch) {
    Write-Host 'Watching Android/Core source changes. Save a file to rebuild and restart. Ctrl+C stops watching.'
    $watchers = @('dotnet/Lala.Android', 'dotnet/Lala.Core', 'dotnet/Lala.Desktop/Shared') | ForEach-Object {
        $watcher = [IO.FileSystemWatcher]::new((Join-Path $AndroidPreviewRepository $_))
        $watcher.IncludeSubdirectories = $true; $watcher.EnableRaisingEvents = $true; $watcher
    }
    $subscriptions = @()
    for ($index = 0; $index -lt $watchers.Count; $index++) {
        foreach ($eventName in @('Changed', 'Created', 'Deleted', 'Renamed')) {
            $eventId = "LalaAndroidPreview.$PID.$index.$eventName"
            $subscriptions += $eventId
            Register-ObjectEvent -InputObject $watchers[$index] -EventName $eventName -SourceIdentifier $eventId | Out-Null
        }
    }
    try {
        while ($true) {
            Start-Sleep -Milliseconds 700
            $changed = $false
            foreach ($eventId in $subscriptions) {
                foreach ($change in @(Get-Event -SourceIdentifier $eventId -ErrorAction SilentlyContinue)) {
                    $name = $change.SourceEventArgs.Name
                    if ($name -notmatch '(^|[\\/])(bin|obj)([\\/]|$)' -and $name -match '\.(cs|csproj|props|xml|json|axaml|png)$') { $changed = $true }
                    Remove-Event -EventIdentifier $change.EventIdentifier
                }
            }
            if ($changed) { Start-Sleep -Milliseconds 700; Update-AndroidPreview }
        }
    }
    finally {
        foreach ($eventId in $subscriptions) { Unregister-Event -SourceIdentifier $eventId -ErrorAction SilentlyContinue; Get-Event -SourceIdentifier $eventId -ErrorAction SilentlyContinue | Remove-Event }
        foreach ($watcher in $watchers) { $watcher.Dispose() }
    }
}
