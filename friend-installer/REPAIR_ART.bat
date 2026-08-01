@echo off
setlocal
title Repair Willex's Whimsical Arts
set "UPDATER=%LOCALAPPDATA%\AlexCockatriceAltArt\Cockatrice_Alt_Art_Updater.ps1"
if not exist "%UPDATER%" set "UPDATER=%~dp0Cockatrice_Alt_Art_Updater.ps1"

echo Close Cockatrice before continuing.
echo.
echo This will:
echo   - install exactly one current XML;
echo   - quarantine duplicate/numbered copies from this pack;
echo   - quarantine matching filesystem-cached art;
echo   - quarantine Cockatrice's network image cache so pictures redownload cleanly.
echo.
echo Nothing is permanently deleted. Recovery files stay in:
echo   %LOCALAPPDATA%\AlexCockatriceAltArt\quarantine
echo.
choice /C YN /N /M "Run repair? [Y/N] "
if errorlevel 2 exit /b 0

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%UPDATER%" -RepairPictures
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
  echo Repair did not finish. Read the error above or send Alex a screenshot.
) else (
  echo Repair finished. Keep picture downloads enabled and reopen Cockatrice.
)
pause
exit /b %RESULT%
