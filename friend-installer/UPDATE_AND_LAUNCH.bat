@echo off
setlocal
title Update Willex's Whimsical Arts
set "UPDATER=%LOCALAPPDATA%\AlexCockatriceAltArt\Cockatrice_Alt_Art_Updater.ps1"
if not exist "%UPDATER%" set "UPDATER=%~dp0Cockatrice_Alt_Art_Updater.ps1"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%UPDATER%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo Update failed. Nothing unverified was installed.
  pause
)
exit /b %RESULT%
