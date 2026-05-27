@echo off
setlocal

echo  ampm-analysis setup
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found on PATH.
    echo  Install Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    if %%a LSS 3 (
        echo  ERROR: Python 3.11+ required, found %PYVER%
        pause
        exit /b 1
    )
    if %%a EQU 3 if %%b LSS 11 (
        echo  ERROR: Python 3.11+ required, found %PYVER%
        pause
        exit /b 1
    )
)
echo  Found Python %PYVER%

if exist .venv (
    echo  .venv already exists, skipping creation
) else (
    echo  Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo  ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo  Installing dependencies...
call .venv\Scripts\activate.bat
pip install -e . --quiet
if errorlevel 1 (
    echo  ERROR: pip install failed.
    pause
    exit /b 1
)

echo.
echo  Done!
pause