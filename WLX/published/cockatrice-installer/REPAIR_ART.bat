@echo off
setlocal
title Repair Willex's Whimsical Arts
set "BOOTSTRAP=%LOCALAPPDATA%\WillexsWhimsicalArts\WLX_Bootstrap.ps1"
if not exist "%BOOTSTRAP%" set "BOOTSTRAP=%~dp0WLX_Bootstrap.ps1"

echo Close Cockatrice before continuing.
echo.
echo This will:
echo   - install exactly one current XML;
echo   - quarantine duplicate or numbered copies from this pack;
echo   - quarantine matching filesystem-cached art;
echo   - quarantine Cockatrice's network image cache so pictures redownload cleanly.
echo.
echo Nothing is permanently deleted. Recovery files stay in:
echo   %LOCALAPPDATA%\WillexsWhimsicalArts\quarantine
echo.
choice /C YN /N /M "Run repair? [Y/N] "
if errorlevel 2 exit /b 0

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%" -RepairPictures
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
  echo Repair did not finish. Read the error above or send the repository owner a screenshot.
) else (
  echo Repair finished. Keep picture downloads enabled and reopen Cockatrice.
)
pause
exit /b %RESULT%
