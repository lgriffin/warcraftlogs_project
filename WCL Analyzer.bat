@echo off
title WCL Analyzer
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>&1
    if not errorlevel 1 (
        ".venv\Scripts\python.exe" -m warcraftlogs_client.gui.app
        goto :done
    )
    echo Existing .venv is broken. Recreating...
    rmdir /s /q .venv
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
    call ".venv\Scripts\activate.bat"
    pip install -r requirements.txt
    python -m warcraftlogs_client.gui.app
    goto :done
)

python -m warcraftlogs_client.gui.app

:done
if errorlevel 1 (
    echo.
    echo Something went wrong. Make sure Python and dependencies are installed.
    echo Run: python -m pip install -r requirements.txt
    pause
)
