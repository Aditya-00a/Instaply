@echo off
REM Wrapper for scheduled watchdog runs. Uses venv python, with toast on issues.
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\agent_watchdog.py --toast --quiet >> artifacts\watchdog_run.log 2>&1
exit /b %ERRORLEVEL%
