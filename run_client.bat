@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python -m wlre.launcher 
) else (
  py -3 -m wlre.launcher 
)
if errorlevel 1 pause
