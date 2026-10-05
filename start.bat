@echo off
setlocal
cd /d "%~dp0"

echo.
echo  InventorySync
echo  ---------------------------------
echo.

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found.
    echo  Install Python 3.11+ from https://python.org
    echo  Make sure to check "Add Python to PATH" during install.
    pause & exit /b 1
)

:: If venv is broken or missing, recreate it
if exist ".venv\Scripts\python.exe" (
    echo  Using existing virtual environment...
) else (
    if exist ".venv" rmdir /s /q ".venv"
    echo  Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo  ERROR: Could not create virtual environment.
        pause & exit /b 1
    )
)

call .venv\Scripts\activate.bat

:: Upgrade pip silently, then install deps
echo  Installing / checking dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet

if errorlevel 1 (
    echo.
    echo  WARNING: Some packages may not have installed correctly.
    echo  The app will try to start anyway.
    echo.
)

echo.
echo  Open http://localhost:5000 in your browser
echo  Press Ctrl+C to stop.
echo.
python app.py
pause
