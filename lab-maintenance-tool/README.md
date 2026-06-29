# Lab Maintenance Tool

Automatically collects YJR lab status and emails a formatted HTML report daily.

## What it does

- **Pings** every machine to determine reachability (Windows/macOS/Linux aware)
- **Fetches ACME status** from each machine's HTTP endpoint
- **SSH + adb** to count iOS/FOS/3P devices and check battery & Wi-Fi state
- **Auto-generates callouts** (unreachable machines, macOS version drift)
- **Sends an HTML email** via SMTP (Gmail, Outlook, etc.) or AWS SES
- **Scheduled daily** via cron (Linux/macOS) or Windows Task Scheduler

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Edit `config.yaml`

Key fields to update:

| Field | Description |
|---|---|
| `schedule.time` | Daily send time in 24h format (`"09:00"`) |
| `schedule.timezone` | Your local timezone (`"Asia/Kolkata"`) |
| `email.sender` | From address |
| `email.recipients` | List of To addresses |
| `email.smtp_host/port` | Your SMTP server |
| `machines[].ip` | IP of each lab machine |
| `ssh.username` | SSH login user on lab machines |
| `ssh.key_path` | Path to SSH private key |
| `acme.endpoint_template` | URL pattern of your ACME status API |

### 3. Set credentials via environment variables

```bash
# SMTP auth
export SMTP_USER="your@email.com"
export SMTP_PASS="your-app-password"

# SSH password (if not using key)
export SSH_PASS="ssh-password"

# AWS SES (if use_ses: true)
export AWS_SES_REGION="us-east-1"
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
```

### 4. Run immediately (for testing)

```bash
python scheduler.py --run-now
```

### 5. Install as a scheduled daily job

```bash
# Linux / macOS — installs a crontab entry
python scheduler.py --install

# Windows — registers a Task Scheduler task (run as Administrator)
python scheduler.py --install
```

### 6. Run the scheduler manually (keeps running in foreground)

```bash
python scheduler.py
```

## Adapting to your environment

### ACME status
Edit `collectors/acme_collector.py` — change the JSON key or URL structure to match your actual ACME API.

### FOS serial prefix
Edit `collectors/device_collector.py` — update `_FOS_SERIAL_PATTERN` to match your FOS device serial numbers.

### macOS target version
Edit `lab_report.py` — change `target = "15.7.7"` in `build_auto_callouts()`.

### Manual callouts
Pass extra strings when calling `run_report()` programmatically:
```python
from lab_report import run_report
run_report(extra_callouts=["Automation is running on GN434P0232770035 in Android Perf-2."])
```

## File structure

```
lab-maintenance-tool/
├── config.yaml              # All configuration
├── scheduler.py             # Entry point & OS scheduler installer
├── lab_report.py            # Orchestration: collect → build → send
├── requirements.txt
├── collectors/
│   ├── ping_collector.py    # Cross-platform ping
│   ├── acme_collector.py    # ACME HTTP status fetch
│   ├── ssh_collector.py     # paramiko SSH helpers
│   ├── adb_collector.py     # adb device listing & checks
│   └── device_collector.py  # iOS/FOS/3P device counting
└── reporters/
    ├── html_report.py       # HTML email builder
    └── email_sender.py      # SMTP & SES sender
```
