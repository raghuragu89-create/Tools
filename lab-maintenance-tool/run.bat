@echo off
title Lab Maintenance Tool - Touchless Automation
color 0A
echo.
echo  ======================================================
echo    Lab Maintenance Tool - Touchless Automation
echo    Rendering Lab (YJ) - 2026 Edition
echo  ======================================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    python3 --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo  [ERROR] Python not found!
        echo  Install from: https://www.python.org/downloads/
        echo  Make sure to check "Add Python to PATH" during install.
        pause
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)

echo  [OK] Python found:
%PYTHON% --version
echo.

:: Install dependencies (first run only)
if not exist ".deps_installed" (
    echo  [SETUP] Installing dependencies (first run only)...
    %PYTHON% -m pip install -r requirements.txt --quiet
    if %errorlevel% equ 0 (
        echo OK > .deps_installed
        echo  [OK] Dependencies installed.
    ) else (
        echo  [WARN] Some dependencies failed. Tool may still work.
    )
    echo.
)

:: Menu
:menu
echo  ======================================================
echo   Choose an option:
echo  ======================================================
echo.
echo   [1] Run Daily Health Report (now)
echo   [2] Run Weekly Restart (dry-run / safe)
echo   [3] Run Weekly Restart (LIVE - restarts devices)
echo   [4] Run IP Discovery only
echo   [5] Install as Daily Scheduled Task
echo   [6] Start Scheduler (runs in background)
echo   [7] Edit Configuration (config.yaml)
echo   [8] View Last Report
echo   [9] Exit
echo.
set /p choice="  Enter choice (1-9): "

if "%choice%"=="1" goto run_report
if "%choice%"=="2" goto restart_dry
if "%choice%"=="3" goto restart_live
if "%choice%"=="4" goto ip_discovery
if "%choice%"=="5" goto install
if "%choice%"=="6" goto scheduler
if "%choice%"=="7" goto edit_config
if "%choice%"=="8" goto view_report
if "%choice%"=="9" goto end
echo  Invalid choice. Try again.
echo.
goto menu

:run_report
echo.
echo  [RUNNING] Daily Health Report...
echo  ======================================================
%PYTHON% scheduler.py --run-now
echo.
echo  ======================================================
echo  [DONE] Report complete. Check your email.
echo.
pause
goto menu

:restart_dry
echo.
echo  [RUNNING] Weekly Restart (DRY RUN - no actual reboot)...
echo  ======================================================
%PYTHON% scheduler.py --restart-dry
echo.
echo  ======================================================
echo  [DONE] Dry run complete. No devices were restarted.
echo.
pause
goto menu

:restart_live
echo.
echo  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo  !! WARNING: This will RESTART all Android devices  !!
echo  !! Make sure no automation is running!             !!
echo  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo.
set /p confirm="  Are you sure? (yes/no): "
if /i "%confirm%"=="yes" (
    %PYTHON% scheduler.py --restart-now
) else (
    echo  Cancelled.
)
echo.
pause
goto menu

:ip_discovery
echo.
echo  [RUNNING] IP Discovery...
echo  ======================================================
%PYTHON% collectors/ip_discovery.py --update
echo.
pause
goto menu

:install
echo.
echo  [INSTALLING] Daily scheduled task (09:00 every day)...
%PYTHON% scheduler.py --install
echo.
echo  [DONE] Task installed. Will run daily at 09:00.
echo.
pause
goto menu

:scheduler
echo.
echo  [STARTING] Background scheduler...
echo  (Press Ctrl+C to stop)
echo  ======================================================
%PYTHON% scheduler.py
goto menu

:edit_config
echo.
echo  Opening config.yaml in Notepad...
notepad config.yaml
goto menu

:view_report
echo.
if exist "report_preview.html" (
    start report_preview.html
    echo  [OK] Opened report in browser.
) else (
    echo  [INFO] No report generated yet. Run option 1 first.
)
echo.
pause
goto menu

:end
echo.
echo  Goodbye!
exit /b 0
