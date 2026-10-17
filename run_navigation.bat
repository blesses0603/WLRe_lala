@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python -m wlre.launcher --navigation
) else (
  py -3 -m wlre.launcher --navigation
)
if errorlevel 1 pause
