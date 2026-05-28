@echo off
setlocal

cd /d "%~dp0"

set "WT_COLUMNS=120"
set "WT_LINES=35"
set "PROJECT_DIR=%CD%"
set "INSIDE_WT="

if /I "%~1"=="--inside-wt" (
    set "INSIDE_WT=1"
    shift /1
)

set "APP_ARGS="
:collect_args
if "%~1"=="" goto args_done
set "APP_ARGS=%APP_ARGS% "%~1""
shift /1
goto collect_args
:args_done

if not defined INSIDE_WT if not defined WT_SESSION (
    where wt.exe >nul 2>&1
    if not errorlevel 1 (
        wt.exe -w 0 --size %WT_COLUMNS%,%WT_LINES% -d "%PROJECT_DIR%" cmd.exe /k call "%~f0" --inside-wt %APP_ARGS%
        exit /b 0
    )
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py %APP_ARGS%
) else (
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        python main.py %APP_ARGS%
    ) else (
        py -3 main.py %APP_ARGS%
    )
)

if errorlevel 1 (
    echo.
    echo The app exited with an error.
    pause
)
