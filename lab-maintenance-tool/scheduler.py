"""
Daily scheduler — runs lab_report.py at the configured time every day.
Also schedules weekly device restarts (if enabled in config).
Supports Windows, macOS, and Linux.

Usage:
    python scheduler.py                  # run scheduler (blocking)
    python scheduler.py --run-now        # fire the report immediately, then exit
    python scheduler.py --restart-now    # fire the weekly restart immediately
    python scheduler.py --restart-dry    # dry-run restart (no actual reboot)
    python scheduler.py --install        # install as OS service/cron
"""
import argparse
import sys
import os
import time

try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    SCHEDULE_AVAILABLE = False

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def get_schedule_time() -> str:
    if YAML_AVAILABLE and os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("schedule", {}).get("time", "09:00")
    return "09:00"


def job():
    print(f"[scheduler] Firing daily report...")
    from lab_report import run_report
    run_report(CONFIG_PATH)


def restart_job():
    print(f"[scheduler] Firing weekly restart...")
    from restarter import run_weekly_restart
    if YAML_AVAILABLE and os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
        run_weekly_restart(cfg)
    else:
        print("[scheduler] Config not found for restart.")


def run_scheduler():
    if not SCHEDULE_AVAILABLE:
        print("ERROR: 'schedule' package not installed. Run: pip install schedule")
        sys.exit(1)

    run_time = get_schedule_time()
    print(f"[scheduler] Daily report at {run_time}. Press Ctrl+C to stop.")
    schedule.every().day.at(run_time).do(job)

    # Weekly restart schedule (if enabled)
    if YAML_AVAILABLE and os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
        restart_cfg = cfg.get("restart", {})
        if restart_cfg.get("enabled"):
            restart_day = restart_cfg.get("day", "sunday").lower()
            restart_time = restart_cfg.get("time", "02:00")
            getattr(schedule.every(), restart_day).at(restart_time).do(restart_job)
            print(f"[scheduler] Weekly restart on {restart_day} at {restart_time}.")

    while True:
        schedule.run_pending()
        time.sleep(30)


def install_cron_linux(run_time: str):
    """Add a crontab entry on Linux/macOS."""
    hour, minute = run_time.split(":")
    script_dir  = os.path.dirname(os.path.abspath(__file__))
    python_exec = sys.executable
    cron_line   = f"{minute} {hour} * * * cd {script_dir} && {python_exec} scheduler.py --run-now >> {script_dir}/lab_report.log 2>&1"

    import subprocess
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    if "scheduler.py" in existing:
        print("[install] Cron entry already exists. Remove it from crontab -e manually first.")
        return

    new_crontab = existing.rstrip() + "\n" + cron_line + "\n"
    proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True)
    if proc.returncode == 0:
        print(f"[install] Cron job installed: runs daily at {run_time}")
    else:
        print("[install] Failed to install cron job.")


def install_windows_task(run_time: str):
    """Register a Windows Task Scheduler task."""
    import subprocess
    hour, minute = run_time.split(":")
    script_dir   = os.path.dirname(os.path.abspath(__file__))
    python_exec  = sys.executable
    task_name    = "LabMaintenanceReport"
    cmd = (
        f'schtasks /Create /F /TN "{task_name}" '
        f'/TR "cmd /c cd /d {script_dir} && {python_exec} scheduler.py --run-now >> {script_dir}\\lab_report.log 2>&1" '
        f'/SC DAILY /ST {hour}:{minute}'
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"[install] Windows Task Scheduler job '{task_name}' installed at {run_time}.")
    else:
        print(f"[install] Failed: {result.stderr}")


def install_service():
    run_time = get_schedule_time()
    if sys.platform == "win32":
        install_windows_task(run_time)
    else:
        install_cron_linux(run_time)


def main():
    parser = argparse.ArgumentParser(description="Lab Maintenance Report Scheduler")
    parser.add_argument("--run-now",      action="store_true", help="Run the report once immediately")
    parser.add_argument("--install",      action="store_true", help="Install as OS scheduled task/cron")
    parser.add_argument("--restart-now",  action="store_true", help="Run weekly restart immediately")
    parser.add_argument("--restart-dry",  action="store_true", help="Dry-run restart (no actual reboot)")
    args = parser.parse_args()

    if args.install:
        install_service()
    elif args.run_now:
        job()
    elif args.restart_now:
        restart_job()
    elif args.restart_dry:
        from restarter import run_weekly_restart
        if YAML_AVAILABLE and os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                cfg = yaml.safe_load(f)
            run_weekly_restart(cfg, dry_run=True)
    else:
        run_scheduler()


if __name__ == "__main__":
    main()
