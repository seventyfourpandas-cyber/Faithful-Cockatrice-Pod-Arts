@echo off
setlocal
title Uninstall Willex's Whimsical Arts
set "UPDATER=%LOCALAPPDATA%\WillexsWhimsicalArts\WLX_Cockatrice_Updater.ps1"
if not exist "%UPDATER%" set "UPDATER=%~dp0WLX_Cockatrice_Updater.ps1"

echo This removes only Willex's Whimsical Arts from Cockatrice.
echo The XML will be moved to a recoverable "removed" folder.
choice /C YN /N /M "Continue? [Y/N] "
if errorlevel 2 exit /b 0
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%UPDATER%" -Uninstall
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
