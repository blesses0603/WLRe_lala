[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'AndroidPreview.Common.ps1')
$androidDevelopment = Join-Path $env:USERPROFILE '.lala-dev'
New-Item -ItemType Directory -Path $androidDevelopment -Force | Out-Null
if (-not (Test-Path -LiteralPath $AndroidPreviewDotnet)) {
    $installer = Join-Path $androidDevelopment 'dotnet-install.ps1'
    Invoke-WebRequest 'https://dot.net/v1/dotnet-install.ps1' -OutFile $installer
    & $installer -Version '10.0.403' -InstallDir (Split-Path $AndroidPreviewDotnet) -NoPath
    if (-not (Test-Path -LiteralPath $AndroidPreviewDotnet)) { throw 'The local .NET SDK installation did not finish.' }
}
$env:DOTNET_ROOT = Split-Path $AndroidPreviewDotnet
$workloads = & $AndroidPreviewDotnet workload list
if (($workloads -join "`n") -notmatch '(?m)^android\s') {
    Invoke-AndroidPreviewCommand $AndroidPreviewDotnet workload install android --skip-manifest-update --disable-parallel
}
if (-not $env:JAVA_HOME -or -not (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME 'bin/javac.exe'))) {
    $java = Get-Command javac.exe -ErrorAction SilentlyContinue
    if (-not $java) { throw 'JDK 21 is required. Install a JDK and set JAVA_HOME, then run setup again.' }
    $env:JAVA_HOME = Split-Path (Split-Path $java.Source)
}
$sdkManager = Join-Path $AndroidPreviewSdk 'cmdline-tools/latest/bin/sdkmanager.bat'
if (-not (Test-Path -LiteralPath $sdkManager)) {
    $repository = Join-Path $androidDevelopment 'repository2-3.xml'
    Invoke-WebRequest 'https://dl.google.com/android/repository/repository2-3.xml' -OutFile $repository
    [xml]$packages = Get-Content -LiteralPath $repository -Raw
    $package = $packages.SelectSingleNode("//*[local-name()='remotePackage' and @path='cmdline-tools;latest']")
    $archive = $package.SelectSingleNode("./*[local-name()='archives']/*[local-name()='archive'][*[local-name()='host-os']='windows']/*[local-name()='complete']")
    if (-not $archive) { throw 'No Windows Android command-line tools were listed by Google.' }
    $relative = $archive.SelectSingleNode("./*[local-name()='url']").InnerText
    if ($relative -notmatch '^commandlinetools-win-[0-9]+_latest\.zip$') { throw 'Unexpected Android tools archive name.' }
    $digest = $archive.SelectSingleNode("./*[local-name()='checksum']").InnerText
    $zip = Join-Path $androidDevelopment 'android-commandline-tools.zip'
    if (-not (Test-Path -LiteralPath $zip) -or (Get-FileHash -LiteralPath $zip -Algorithm SHA1).Hash -ine $digest) {
        Invoke-WebRequest ('https://dl.google.com/android/repository/' + $relative) -OutFile $zip
    }
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA1).Hash -ine $digest) { throw 'Android tools checksum mismatch.' }
    $extracted = Join-Path $androidDevelopment 'android-commandline-tools'
    Expand-Archive -LiteralPath $zip -DestinationPath $extracted -Force
    New-Item -ItemType Directory -Path (Split-Path (Split-Path $sdkManager)) -Force | Out-Null
    Copy-Item -Path (Join-Path $extracted 'cmdline-tools/*') -Destination (Split-Path (Split-Path $sdkManager)) -Recurse -Force
}
Write-Host 'Installing the SDK, emulator and API 36 preview image. First setup may take several minutes.'
$androidCli = Join-Path $AndroidPreviewSdk 'cmdline-tools/latest/bin/android.exe'
if (Test-Path -LiteralPath $androidCli) {
    # Current Android CLI uses slash paths; avoid the deprecated batch wrapper's
    # semicolon splitting on Windows.
    Invoke-AndroidPreviewCommand $androidCli "--sdk=$AndroidPreviewSdk" sdk install 'platform-tools' 'platforms/android-36' 'build-tools/36.0.0' 'emulator'
    Invoke-AndroidPreviewCommand $androidCli "--sdk=$AndroidPreviewSdk" sdk install ($AndroidPreviewImage.Replace(';', '/'))
}
else {
    1..12 | ForEach-Object { 'y' } | & $sdkManager "--sdk_root=$AndroidPreviewSdk" --licenses | Out-File (Join-Path $androidDevelopment 'android-sdk-licenses.log') -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw 'Android SDK license setup failed.' }
    Invoke-AndroidPreviewCommand $sdkManager "--sdk_root=$AndroidPreviewSdk" 'platform-tools' 'platforms;android-36' 'build-tools;36.0.0' 'emulator' $AndroidPreviewImage
}
$avdManager = Join-Path $AndroidPreviewSdk 'cmdline-tools/latest/bin/avdmanager.bat'
$available = & (Join-Path $AndroidPreviewSdk 'emulator/emulator.exe') -list-avds
if ($available -notcontains $AndroidPreviewAvd) {
    'no' | & $avdManager create avd --name $AndroidPreviewAvd --package $AndroidPreviewImage --device pixel_7
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the preview virtual device.' }
}
Write-Host 'Android preview setup is ready. Run run_android_preview.bat from the repository.'
