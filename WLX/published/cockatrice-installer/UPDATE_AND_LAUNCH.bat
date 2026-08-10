@echo off
setlocal
title Update Willex's Whimsical Arts
set "BOOTSTRAP=%LOCALAPPDATA%\WillexsWhimsicalArts\WLX_Bootstrap.ps1"
if not exist "%BOOTSTRAP%" set "BOOTSTRAP=%~dp0WLX_Bootstrap.ps1"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo Update failed. Nothing unverified was installed.
  pause
)
exit /b %RESULT%
