@echo off
REM BladeForm launcher — starts the local helper (127.0.0.1 only) and opens the viewer through it.
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found on PATH. Install Python 3 and try again.
  pause
  exit /b 1
)

echo Starting BladeForm helper on http://127.0.0.1:8765/ ...
start "BladeForm helper" /min python helper.py

REM Give the server a moment to bind.
timeout /t 2 /nobreak >nul

start "" "http://127.0.0.1:8765/"
echo Viewer opened. Leave the helper window running while you work.
echo Close the helper window when you are finished.
endlocal
