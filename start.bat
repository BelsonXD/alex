@echo off
setlocal
cd /d "%~dp0"
title ALEX
where powershell >nul 2>&1
if errorlevel 1 (
  echo PowerShell is required to set up ALEX.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo.
  echo ALEX did not start. Read the messages above.
  pause
  exit /b 1
)
endlocal
