@echo off
REM Runs the watchdog with --autorestart so critical states self-heal.
REM Scheduled by Task Scheduler (InstaplyAgent-AutoRestart), every 5 minutes.

cd /d "%~dp0.."
python scripts\agent_watchdog.py --quiet --autorestart
