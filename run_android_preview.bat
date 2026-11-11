@echo off
setlocal
cd /d "%~dp0"
title LALA Android Preview
echo Starting LALA Android preview. Keep this window open while editing.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0tools\android\Run-AndroidPreview.ps1" -Watch
echo.
echo The preview launcher has stopped. Startup logs are in:
echo %LOCALAPPDATA%\LaLa\AndroidPreview\Logs
pause
