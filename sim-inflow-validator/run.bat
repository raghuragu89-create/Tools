@echo off
REM ═══════════════════════════════════════════════════════════════════
REM SIM Inflow Validator — Windows Task Scheduler (every 5 min)
REM ═══════════════════════════════════════════════════════════════════

C:\Windows\System32\wsl.exe -d AmazonWSL -- bash -lc "/home/your-username/sim-validator-cron.sh"
