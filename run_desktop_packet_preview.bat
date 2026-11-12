@echo off
setlocal
cd /d "%~dp0"
set "LALA_PACKET_DOTNET=%USERPROFILE%\.lala-dev\dotnet\dotnet.exe"
if exist "%LALA_PACKET_DOTNET%" goto build_preview
set "LALA_PACKET_DOTNET=dotnet"
where dotnet >nul 2>&1
if errorlevel 1 goto missing_sdk

:build_preview
echo Building LALA desktop preview. Close the previous preview window first.
"%LALA_PACKET_DOTNET%" build "dotnet\Lala.Desktop\Lala.Desktop.csproj" --configuration Debug --artifacts-path "dotnet\Lala.Desktop\obj\packet-preview-artifacts" --output "dotnet\Lala.Desktop\bin\packet-audit-check" --disable-build-servers -p:UseSharedCompilation=false --nologo --verbosity minimal
if errorlevel 1 goto failed
"%LALA_PACKET_DOTNET%" "dotnet\Lala.Desktop\bin\packet-audit-check\Lala.Desktop.dll" %*
set "LALA_PACKET_RESULT=%errorlevel%"
if not "%LALA_PACKET_RESULT%"=="0" goto failed
exit /b 0

:missing_sdk
echo LALA desktop preview requires the .NET 10 SDK.
pause
exit /b 1

:failed
echo Preview could not complete. Close the previous preview and review the messages above.
pause
exit /b 1
