@echo off
setlocal
title Uninstall Alex's Cockatrice Alternate Art
set "UPDATER=%LOCALAPPDATA%\AlexCockatriceAltArt\Cockatrice_Alt_Art_Updater.ps1"
if not exist "%UPDATER%" set "UPDATER=%~dp0Cockatrice_Alt_Art_Updater.ps1"

echo This removes only Alex's Cockatrice Alternate Art from Cockatrice.
echo The XML will be moved to a recoverable "removed" folder.
choice /C YN /N /M "Continue? [Y/N] "
if errorlevel 2 exit /b 0
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%UPDATER%" -Uninstall
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
