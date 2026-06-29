# Lab Maintenance Tool — Complete Usage Guide

## 📋 Quick Start (TL;DR)

```bash
cd lab-maintenance-tool
pip3 install -r requirements.txt
# Edit config.yaml with your lab details
python3 scheduler.py --run-now
```

---

## 🔧 What You Need to Provide (Inputs)

### Mandatory Inputs (in `config.yaml`):

| Input | Where | Example | Why |
|-------|-------|---------|-----|
| **Machine IPs** | `machines[].ip` | `10.0.0.1` | Tool pings these to check health |
| **Machine types** | `machines[].type` | `android`, `ios`, `generic` | Determines what checks to run |
| **SSH username** | `ssh.username` | `your-ssh-user` | For remote ADB/device commands |
| **SSH key or password** | `ssh.key_path` or env `SSH_PASS` | `~/.ssh/id_rsa` | Auth for SSH connections |
| **Email recipients** | `email.recipients` | `yjar-team@amazon.com` | Who gets the daily report |
| **Email credentials** | env `SMTP_USER` + `SMTP_PASS` | (SES creds) | SMTP authentication |

### Optional Inputs (enhance accuracy):

| Input | Where | Purpose |
|-------|-------|---------|
| `machines[].hostname` | config.yaml | DNS-based IP discovery |
| `machines[].mac_address` | config.yaml | ARP-based IP discovery (for DHCP) |
| `machines[].jenkins_node` | config.yaml | Links machine to Jenkins node |
| `jenkins.url` | config.yaml | Jenkins monitoring |
| `jenkins.username` + `api_token` | config.yaml or env | Jenkins API auth |
| `thresholds.battery_min_percent` | config.yaml | Custom battery warning level (default: 80%) |
| `thresholds.macos_target_version` | config.yaml | Expected macOS version |
| `discovery.subnet` | config.yaml | Subnet for ping-sweep IP discovery |
| `restart.day` + `restart.time` | config.yaml | Weekly restart schedule |

### What is Auto-Detected (no input needed):

| Data | How it's collected |
|------|-------------------|
| Machine reachability | ICMP ping |
| ACME compliance status | HTTP GET to ACME endpoint |
| ADB connected devices | `adb devices` via SSH |
| Battery level per device | `adb shell dumpsys battery` via SSH |
| WiFi status per device | `adb shell dumpsys wifi` via SSH |
| iOS device count | `idevice_id -l` via SSH |
| macOS version | `sw_vers -productVersion` via SSH |
| Jenkins node status | Jenkins REST API |
| Jenkins job build results | Jenkins REST API |
| IP address changes | Hostname/MAC/ARP/ping discovery |

---

## 📦 Step-by-Step Setup

### Step 1: Install Python Dependencies

```bash
cd lab-maintenance-tool
pip3 install -r requirements.txt
```

**Dependencies:**
- `paramiko` — SSH connections
- `PyYAML` — Config file parsing
- `schedule` — Daily/weekly job scheduling
- `boto3` — (Optional) AWS SES email

### Step 2: Configure `config.yaml`

```bash
# Open config for editing
nano config.yaml    # Linux/Mac
notepad config.yaml # Windows
```

**Minimum required changes:**

```yaml
# 1. Update machine IPs to match your lab
machines:
  - name: "Android Perf-0"
    ip: "10.0.0.1"       # ← Your actual IP
    type: "android"
    adb_host: true
    hostname: ""              # ← Fill if DNS available
    mac_address: ""           # ← Fill if known (for DHCP)

# 2. Set SSH credentials
ssh:
  username: "your-ssh-user"        # ← Lab machine login
  key_path: "~/.ssh/id_rsa"  # ← Path to SSH key
  password: ""                # ← Or set env SSH_PASS

# 3. Configure email
email:
  smtp_host: "email-smtp.us-east-1.amazonaws.com"
  smtp_port: 587
  use_tls: true
  sender: "your-email@example.com"
  recipients:
    - "yjar-team@amazon.com"
```

### Step 3: Set Environment Variables

```bash
# Linux/Mac
export SMTP_USER="your_ses_smtp_username"
export SMTP_PASS="your_ses_smtp_password"
export SSH_PASS="YOUR_SSH_PASSWORD"  # Only if not using SSH keys

# Windows CMD
set SMTP_USER=your_ses_smtp_username
set SMTP_PASS=your_ses_smtp_password
set SSH_PASS=YOUR_SSH_PASSWORD
```

### Step 4: Validate Setup (Dry Run)

```bash
# Test the full report (generates HTML but skips email if creds are wrong)
python3 scheduler.py --run-now
```

**Expected output:**
```
[scheduler] Firing daily report...
[report] Running IP discovery...
  Android Perf-0: static IP 10.0.0.1 still reachable ✓
  Android Perf-1: static IP 10.0.0.2 still reachable ✓
  ...
  No IP changes detected.
[report] Collecting machine status...
[report] Counting devices...
[report] Checking Jenkins nodes...
[report] Checking Android Perf status...
[report] Building HTML...
[report] Sending via SMTP...
[report] ✓ Report sent to ['yjar-team@amazon.com']
```

### Step 5: Test Weekly Restart (Dry Run)

```bash
python3 scheduler.py --restart-dry
```

**Expected output:**
```
[09:00:00] ==================================================
[09:00:00] WEEKLY RESTART ROUTINE
[09:00:00] ==================================================
[09:00:01] No automation currently running. Proceeding...
[09:00:01] [DRY RUN] Would restart devices but not executing.
```

### Step 6: Install as Scheduled Service

```bash
# Linux/Mac — installs cron job (daily at 09:00)
python3 scheduler.py --install

# Windows — creates Task Scheduler entry
python scheduler.py --install
```

### Step 7: Verify Scheduled Execution

```bash
# Linux — check crontab
crontab -l | grep lab

# Windows — check Task Scheduler
schtasks /Query /TN "LabMaintenance"
```

---

## 📊 Expected Output

### 1. Console Output (when running manually)

```
[scheduler] Firing daily report...
[report] Running IP discovery...
══════════════════════════════════════════════════
IP DISCOVERY — Finding current machine addresses
══════════════════════════════════════════════════
  Android Perf-0: resolved via hostname → 10.0.0.1
  Android Perf-1: static IP 10.0.0.2 still reachable ✓
  iOS Perf-0: found via Jenkins node 'krq-ios-nft-0' → 10.0.0.5
  KC: IP CHANGED: 10.0.0.7 → 10.144.253.55
  1 IP(s) updated in config.

[report] Collecting machine status...
  ✓ Android Perf-0 (10.0.0.1): reachable, ACME: Green
  ✓ Android Perf-1 (10.0.0.2): reachable, ACME: Green
  ✗ iOS Perf-0 (10.0.0.5): UNREACHABLE

[report] Counting devices...
  Android Perf-0: 7 FOS, 0 3P
  Android Perf-1: 8 FOS, 0 3P
  iOS Perf-0: SSH failed (unreachable)

[report] Checking Jenkins nodes...
  ✓ krq-android-nft-0: Online (idle)
  ✗ krq-ios-nft-0: OFFLINE

[report] Checking Android Perf status...
  Android Perf-0: ADB=Green, Battery=Green (all >80%), WiFi=Green (disabled)
  Android Perf-1: ADB=Green, Battery=RED (device GCC22X: 45%), WiFi=Green

[report] Building HTML...
[report] Sending via SMTP...
[report] ✓ Report sent to ['yjar-team@amazon.com']
```

### 2. Email Report (HTML)

Recipients receive a styled email with:

```
╔══════════════════════════════════════════════════════╗
║  Lab Maintenance Status Report — 2026-06-11        ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  ⚠️ CALLOUTS:                                       ║
║  • iOS Perf-0 (10.0.0.5) is unreachable           ║
║  • Jenkins node 'krq-ios-nft-0' is OFFLINE          ║
║  • Battery low on Android Perf-1 (device GCC22X)    ║
║                                                      ║
║  ┌─ Machine Status ─────────────────────────────┐   ║
║  │ Name           │ IP            │ ACME │ Ping  │   ║
║  │ Android Perf-0 │ 10.0.0.1 │ 🟢   │ 🟢    │   ║
║  │ Android Perf-1 │ 10.0.0.2 │ 🟢   │ 🟢    │   ║
║  │ iOS Perf-0     │ 10.0.0.5     │ 🔴   │ 🔴    │   ║
║  └───────────────────────────────────────────────┘   ║
║                                                      ║
║  ┌─ Device Summary ─────────────────────────────┐   ║
║  │ Host           │ FOS │ 3P │ iOS │ Total      │   ║
║  │ Android Perf-0 │  7  │  0 │  0  │   7        │   ║
║  │ Android Perf-1 │  8  │  0 │  0  │   8        │   ║
║  └───────────────────────────────────────────────┘   ║
║                                                      ║
║  ┌─ Android Performance Nodes ───────────────────┐   ║
║  │ Host           │ ADB │ Battery │ WiFi Off     │   ║
║  │ Android Perf-0 │ 🟢  │  🟢    │  🟢          │   ║
║  │ Android Perf-1 │ 🟢  │  🔴    │  🟢          │   ║
║  └───────────────────────────────────────────────┘   ║
║                                                      ║
║  ┌─ Jenkins Nodes ───────────────────────────────┐   ║
║  │ Node Name        │ Status  │ Idle             │   ║
║  │ krq-android-nft-0│ 🟢     │ Yes              │   ║
║  │ krq-ios-nft-0    │ 🔴     │ -                │   ║
║  └───────────────────────────────────────────────┘   ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
```

### 3. IP History Log (`.ip_history.json`)

Auto-maintained audit trail of IP changes:
```json
[
  {
    "timestamp": "2026-06-11T09:00:15+00:00",
    "changes": {"KC": "10.144.253.55"}
  },
  {
    "timestamp": "2026-06-15T09:00:12+00:00",
    "changes": {"Android Perf-2": "10.144.253.88"}
  }
]
```

---

## 🔄 Daily Workflow (Automatic)

```
09:00 ──┬── IP Discovery (auto-detect changed IPs)
        ├── Ping all machines
        ├── Check ACME compliance
        ├── SSH → count devices, check battery, verify WiFi off
        ├── Query Jenkins API (node status + job results)
        ├── Build HTML report
        └── Email to yjar-team@

02:00 (Sunday) ──┬── Check Jenkins: any automation running?
                 ├── If YES → abort, retry next week
                 └── If NO → restart all Android devices via ADB
```

---

## ✅ Validation Checklist

Run these commands and verify output:

| # | Command | Expected Result |
|---|---------|-----------------|
| 1 | `python3 -c "import paramiko, yaml, schedule; print('OK')"` | `OK` (deps installed) |
| 2 | `python3 scheduler.py --run-now` | Report generated (check console output) |
| 3 | `python3 scheduler.py --restart-dry` | Shows "DRY RUN" (no actual restart) |
| 4 | `python3 collectors/ip_discovery.py` | Lists discovered IPs |
| 5 | `cat .ip_history.json` | Shows IP change history (after first run) |
| 6 | `python3 -c "from collectors.jenkins_collector import *; print('OK')"` | `OK` |
| 7 | Check email inbox | HTML report received |

---

## 🚨 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: No module named 'paramiko'` | Dependencies not installed | `pip3 install -r requirements.txt` |
| `Connection refused` on SSH | Wrong IP or machine off | Check IP in config, verify machine is on |
| `SMTP error: Authentication Required` | Email creds not set | Set `SMTP_USER` and `SMTP_PASS` env vars |
| All machines "UNREACHABLE" | Not on lab network | Run from a machine inside the lab subnet |
| Jenkins "Connection error" | Wrong URL or not on VPN | Verify `jenkins.url` in config, check VPN |
| `Permission denied` on SSH | Wrong key/password | Update `ssh.key_path` or set `SSH_PASS` env |
| Battery shows Green but devices dead | Zero devices = false Green (now fixed) | Update to latest version |
| IP keeps changing | DHCP environment | Fill `mac_address` field in config for ARP discovery |
| `yaml.safe_load` error | Bad YAML syntax | Validate with `python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"` |

---

## 📁 File Structure

```
lab-maintenance-tool/
├── scheduler.py              ← Entry point (CLI)
├── lab_report.py             ← Orchestrator (collect → report → send)
├── restarter.py              ← Weekly device restart
├── config.yaml               ← All configuration
├── requirements.txt          ← Python dependencies
├── .ip_history.json          ← Auto-generated IP change log
├── collectors/
│   ├── ping_collector.py     ← ICMP ping
│   ├── acme_collector.py     ← ACME HTTP status
│   ├── ssh_collector.py      ← SSH client wrapper
│   ├── adb_collector.py      ← ADB device/battery/WiFi
│   ├── device_collector.py   ← iOS/FOS/3P classification
│   ├── jenkins_collector.py  ← Jenkins node + job status
│   └── ip_discovery.py       ← Dynamic IP detection
└── reporters/
    ├── html_report.py        ← HTML email builder
    └── email_sender.py       ← SMTP/SES delivery
```
