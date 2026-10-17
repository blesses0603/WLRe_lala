@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3 -m tools.resources.collect_emoji_resources
if errorlevel 1 pause
exit /b
:usepython
python -m tools.resources.collect_emoji_resources
if errorlevel 1 pause
