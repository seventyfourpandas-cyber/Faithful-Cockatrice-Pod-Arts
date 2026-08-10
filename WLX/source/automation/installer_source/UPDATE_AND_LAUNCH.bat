@echo off
setlocal
title Update __DISPLAY_NAME__
set "BOOTSTRAP=%LOCALAPPDATA%\__INSTALL_FOLDER__\WLX_Bootstrap.ps1"
if not exist "%BOOTSTRAP%" set "BOOTSTRAP=%~dp0WLX_Bootstrap.ps1"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo Update failed. Nothing unverified was installed.
  pause
)
exit /b %RESULT%
