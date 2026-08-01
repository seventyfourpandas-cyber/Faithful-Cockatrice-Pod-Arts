@echo off
setlocal
title Install Alex's Cockatrice Alternate Art
set "INSTALL_DIR=%LOCALAPPDATA%\AlexCockatriceAltArt"

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
for %%F in (Cockatrice_Alt_Art_Updater.ps1 UPDATE_AND_LAUNCH.bat UNINSTALL.bat README_FOR_FRIENDS.txt friend_config.json) do (
  copy /Y "%~dp0%%F" "%INSTALL_DIR%\%%F" >nul
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_DIR%\Cockatrice_Alt_Art_Updater.ps1" -InstallShortcut
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
  echo Installation did not finish. Read the error above or send Alex a screenshot.
) else (
  echo Installation/update finished successfully.
)
pause
exit /b %RESULT%
