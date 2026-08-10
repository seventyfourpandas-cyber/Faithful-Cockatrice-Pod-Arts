@echo off
setlocal
title WLX Cockatrice Installer
set "INSTALL_DIR=%LOCALAPPDATA%\__INSTALL_FOLDER__"

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
for %%F in (WLX_Bootstrap.ps1 WLX_Cockatrice_Updater.ps1 UPDATE_AND_LAUNCH.bat REPAIR_ART.bat UNINSTALL.bat README_FOR_PLAYERS.txt installer_config.json) do (
  copy /Y "%~dp0%%F" "%INSTALL_DIR%\%%F" >nul
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_DIR%\WLX_Bootstrap.ps1" -InstallShortcut
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
  echo Installation did not finish. Read the error above or send the repository owner a screenshot.
) else (
  echo __DISPLAY_NAME__ was installed or updated successfully.
)
pause
exit /b %RESULT%
