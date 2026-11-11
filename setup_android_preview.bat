@echo off
setlocal
cd /d "%~dp0"
title LALA Android Preview - First-time Setup
echo This installs preview tools. It does not open the preview App.
echo For daily preview, use run_android_preview.bat instead.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\android\Setup-AndroidPreview.ps1"
if errorlevel 1 goto failed
echo.
echo Setup finished. To open the emulator and LALA App, double-click:
echo %~dp0run_android_preview.bat
pause
exit /b 0
:failed
echo.
echo Setup failed. Read the error above before closing this window.
pause
exit /b 1
