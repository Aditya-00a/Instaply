@echo off
setlocal EnableDelayedExpansion

:: ============================================================
:: Instaply Job Agent - Daily Cycle Runner
:: Runs the full pipeline: scout, generate packets, send alerts
:: ============================================================

set "REVIZE_ROOT=C:\Ravendise\Instaply"
set "VENV_PYTHON=%REVIZE_ROOT%\.venv\Scripts\python.exe"
set "VENV_ACTIVATE=%REVIZE_ROOT%\.venv\Scripts\activate.bat"
set "API_HOST=127.0.0.1"
set "API_PORT=8002"
set "API_BASE=http://%API_HOST%:%API_PORT%"

:: Set working directory
cd /d "%REVIZE_ROOT%"

:: Create logs directory if needed
if not exist "data\logs" mkdir "data\logs"

:: Build log filename with today's date
for /f "tokens=1-3 delims=-" %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do (
    set "TODAY=%%a-%%b-%%c"
)
set "LOGFILE=data\logs\daily-cycle-%TODAY%.log"

:: Start logging
echo ============================================================ >> "%LOGFILE%"
echo Instaply Daily Cycle - %TODAY% >> "%LOGFILE%"
echo Started: %date% %time% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

:: Activate venv
if exist "%VENV_ACTIVATE%" (
    echo [%time%] Activating virtual environment... >> "%LOGFILE%"
    call "%VENV_ACTIVATE%"
) else (
    echo [%time%] WARNING: venv not found at %VENV_ACTIVATE%, using system Python >> "%LOGFILE%"
)

:: Check if API server is already running
echo [%time%] Checking if API server is running on %API_BASE%... >> "%LOGFILE%"
set "SERVER_WAS_RUNNING=0"
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%API_BASE%/health' -TimeoutSec 3 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [%time%] API server is already running. >> "%LOGFILE%"
    set "SERVER_WAS_RUNNING=1"
    goto :server_ready
)

:: Start the API server in the background
echo [%time%] Starting API server... >> "%LOGFILE%"
if exist "%VENV_PYTHON%" (
    start /B "" "%VENV_PYTHON%" -m uvicorn backend.api.main:app --host %API_HOST% --port %API_PORT% >> "data\logs\api-server-%TODAY%.log" 2>&1
) else (
    start /B "" python -m uvicorn backend.api.main:app --host %API_HOST% --port %API_PORT% >> "data\logs\api-server-%TODAY%.log" 2>&1
)

:: Wait for server to become healthy (poll /health up to 60 seconds)
echo [%time%] Waiting for server to become healthy... >> "%LOGFILE%"
set "HEALTHY=0"
for /L %%i in (1,1,30) do (
    if !HEALTHY! equ 0 (
        timeout /t 2 /nobreak >nul 2>&1
        powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%API_BASE%/health' -TimeoutSec 3 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
        if !ERRORLEVEL! equ 0 (
            set "HEALTHY=1"
            echo [%time%] Server is healthy after %%i attempts. >> "%LOGFILE%"
        )
    )
)

if %HEALTHY% equ 0 (
    echo [%time%] ERROR: API server did not become healthy within 60 seconds. >> "%LOGFILE%"
    echo [%time%] Continuing with CLI-only cycle (no API required for core pipeline)... >> "%LOGFILE%"
)

:server_ready

:: Run the full cycle
echo [%time%] Running full daily cycle (scout + packets + alerts)... >> "%LOGFILE%"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" "%REVIZE_ROOT%\scripts\openclaw_revize.py" cycle >> "%LOGFILE%" 2>&1
) else (
    python "%REVIZE_ROOT%\scripts\openclaw_revize.py" cycle >> "%LOGFILE%" 2>&1
)
set "CYCLE_EXIT=%ERRORLEVEL%"

if %CYCLE_EXIT% neq 0 (
    echo [%time%] WARNING: Cycle exited with code %CYCLE_EXIT% >> "%LOGFILE%"
) else (
    echo [%time%] Cycle completed successfully. >> "%LOGFILE%"
)

:: Final summary
echo ============================================================ >> "%LOGFILE%"
echo Finished: %date% %time% >> "%LOGFILE%"
echo Exit code: %CYCLE_EXIT% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

endlocal
exit /b %CYCLE_EXIT%
