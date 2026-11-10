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
echo Starting LaLa Desktop. First launch may restore NuGet packages and build the app.
dotnet run --project "dotnet\Lala.Desktop\Lala.Desktop.csproj" --configuration Release
set "result=%errorlevel%"
if not "%result%"=="0" (
  echo Desktop could not start. Review the messages above.
  pause
)
exit /b %result%

:missing_sdk
echo LaLa Desktop requires the .NET 10 SDK. A runtime alone is not sufficient.
echo Install it manually from https://dotnet.microsoft.com/download/dotnet/10.0
echo Then double-click run_desktop.bat again. Nothing was installed automatically.
pause
exit /b 1
