@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "WLRE_BUILD_PY="
for %%V in (12 11 10 14 13) do (
  py -3.%%V -m tools.build.python_build_support >nul 2>&1
  if not errorlevel 1 (
    set "WLRE_BUILD_PY=py -3.%%V"
    goto ready
  )
)
python -m tools.build.python_build_support >nul 2>&1
if errorlevel 1 goto no_python
set "WLRE_BUILD_PY=python"
:ready
%WLRE_BUILD_PY% -c "import sys,struct,tkinter; print('Python:',sys.version); print('Bits:',struct.calcsize('P')*8); print('Path:',sys.executable); print('Tk:',tkinter.TkVersion)"
%WLRE_BUILD_PY% -m tools.build.build_nuitka %*
if errorlevel 1 goto failed
echo.
echo BUILD COMPLETE.
pause
exit /b 0
:no_python
echo ERROR: No complete 64-bit Python 3.10-3.14 build installation was found.
echo Checking development libraries and headers:
for %%V in (12 11 10 14 13) do py -3.%%V -m tools.build.python_build_support
echo.
echo Detected Python installations:
py -0p
python -c "import sys,struct; print(sys.version); print('Bits:',struct.calcsize('P')*8); print('Path:',sys.executable); import tkinter; print('Tk:',tkinter.TkVersion)"
echo.
echo Install 64-bit Python 3.12 from https://www.python.org/downloads/windows/
echo Keep Tcl/Tk, development headers/libraries and the Python launcher enabled, then reopen this BAT.
echo This failure happened BEFORE Nuitka. No build report was created.
pause
exit /b 1
:failed
echo.
echo BUILD FAILED. See dist_nuitka for build.log and compilation-report.xml.
pause
exit /b 1
