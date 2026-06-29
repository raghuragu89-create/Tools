@echo off
REM ============================================================
REM TestRail Analyzer — Polling Agent Setup for Windows Scheduler
REM Run this script AS ADMINISTRATOR to create the scheduled task
REM ============================================================

SET TASK_NAME=TestRailAnalyzerAgent
SET SCRIPT_PATH=C:\Users\your-username\Downloads\New folder\pipeline\polling_agent.py
SET PYTHON_PATH=python

REM --- Set API key as system environment variable ---
setx TESTRAIL_KEY "frWDlm1cEOuuIpcWVIdU-IIGEIq7uBHYIayEhMSko" /M

REM --- Stop existing task if running ---
schtasks /end /tn "%TASK_NAME%" >nul 2>&1

REM --- Delete old task if exists ---
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

REM --- Create the scheduled task (auto-restart on logon) ---
schtasks /create /tn "%TASK_NAME%" /tr "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\"" /sc ONLOGON /rl HIGHEST /f

REM --- Start it immediately ---
schtasks /run /tn "%TASK_NAME%"

echo.
echo ============================================================
echo [DONE] "%TASK_NAME%" installed and RUNNING.
echo.
echo  - Auto-starts on logon
echo  - Polls TestRail every 5 min
echo  - Heartbeat refreshes dashboard URL every 24h
echo  - Analyzes only new/updated TCs
echo.
echo Commands:
echo   Status:   schtasks /query /tn "%TASK_NAME%"
echo   Restart:  schtasks /end /tn "%TASK_NAME%" ^& schtasks /run /tn "%TASK_NAME%"
echo   Stop:     schtasks /end /tn "%TASK_NAME%"
echo   Remove:   schtasks /delete /tn "%TASK_NAME%" /f
echo ============================================================
echo.
pause
