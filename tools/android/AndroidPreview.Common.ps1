Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$AndroidPreviewRepository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$AndroidPreviewProject = Join-Path $AndroidPreviewRepository 'dotnet/Lala.Android/Lala.Android.csproj'
$AndroidPreviewDotnet = Join-Path $env:USERPROFILE '.lala-dev/dotnet/dotnet.exe'
$AndroidPreviewSdk = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } elseif ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA 'Android/Sdk' }
$AndroidPreviewAvd = 'LALA_Preview_API36'
$AndroidPreviewImage = 'system-images;android-36;default;x86_64'
if (Test-Path -LiteralPath $AndroidPreviewDotnet) { $env:DOTNET_ROOT = Split-Path $AndroidPreviewDotnet }
$env:ANDROID_HOME = $env:ANDROID_SDK_ROOT = $AndroidPreviewSdk
function Invoke-AndroidPreviewCommand {
    # Keep native flags literal: a PowerShell -c/-p parameter abbreviation must
    # never replace the executable path or consume an adb/sdk option.
    if ($args.Count -eq 0) { throw 'An executable path is required.' }
    $commandPath = [string]$args[0]
    $nativeParameters = @()
    if ($args.Count -gt 1) { $nativeParameters = @($args[1..($args.Count - 1)]) }
    & $commandPath @nativeParameters
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $commandPath" }
}
