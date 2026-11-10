@echo off
setlocal
cd /d "%~dp0"
where dotnet >nul 2>&1
if errorlevel 1 goto missing_sdk
dotnet --list-sdks 2>nul | findstr /b /c:"10." >nul
if errorlevel 1 goto missing_sdk
if not exist "dotnet\Lala.Desktop\Lala.Desktop.csproj" (
  echo Desktop project not found. Keep this BAT in the repository root.
  pause
  exit /b 1
)
echo LaLa Desktop layout preview - save a C# file to rebuild and restart.
echo Keep this console open. Press Ctrl+C to stop watching.
echo Preview uses Debug output, separate from the normal Release launcher.
dotnet watch --project "dotnet\Lala.Desktop\Lala.Desktop.csproj" --no-hot-reload --configuration Debug
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%

:missing_sdk
echo LaLa Desktop preview requires the .NET 10 SDK.
echo Install it manually from https://dotnet.microsoft.com/download/dotnet/10.0
pause
exit /b 1
