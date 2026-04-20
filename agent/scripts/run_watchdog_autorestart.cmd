@echo off
REM Runs the watchdog with --autorestart so critical states self-heal.
REM Scheduled by Task Scheduler (RevizeAgent-AutoRestart), every 5 minutes.

cd /d "C:\Ravendise\Instaply"
python scripts\agent_watchdog.py --quiet --autorestart
