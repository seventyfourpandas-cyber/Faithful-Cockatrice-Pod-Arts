@echo off
setlocal
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo Python was not found.
  echo Install Python, then run: python -m pip install -r requirements-importer.txt
  pause
  exit /b 1
)

python -c "import PIL" >nul 2>&1
if errorlevel 1 (
  echo Installing the image-reading dependency...
  python -m pip install -r requirements-importer.txt
  if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
  )
)

python tools\wlx_importer.py
set code=%errorlevel%

echo.
if "%code%"=="0" (
  echo Import complete.
) else (
  echo Import finished with a problem. Check imports\last-run.json and imports\needs-attention.
)
pause
exit /b %code%
