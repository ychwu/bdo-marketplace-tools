@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        python main.py
    ) else (
        py -3 main.py
    )
)

if errorlevel 1 (
    echo.
    echo The app exited with an error.
    pause
)
