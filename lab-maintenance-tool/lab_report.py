"""
Core orchestration: collects all data, builds the report, sends it.
Run directly or called by the scheduler.
"""
import os
import sys
import yaml
from datetime import date
from typing import Any, Dict, List

from collectors.ping_collector import ping
from collectors.acme_collector import get_acme_status
from collectors.ssh_collector import create_ssh_client, get_macos_version
from collectors.jenkins_collector import get_jenkins_nodes, get_jenkins_job_status, summarize_nodes
from collectors.ip_discovery import discover_ips, update_config_ips


from collectors.kraft_collector import check_all_kraft_devices
from collectors.book_account_collector import check_all_devices_books_and_accounts
from collectors.xcode_collector import check_ios_machines

from collectors.adb_collector import (
    get_remote_devices, count_connected,
    check_wifi_disabled_via_ssh, check_battery_via_ssh,
)
from collectors.device_collector import (
    count_ios_devices_remote, count_android_devices_by_type_remote,
)
from reporters.html_report import build_html
from reporters.email_sender import send_via_smtp, send_via_ses


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def collect_machine_data(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    machines_cfg = cfg["machines"]
    acme_cfg     = cfg.get("acme", {})
    ssh_cfg      = cfg.get("ssh", {})
    adb_binary   = cfg.get("adb", {}).get("binary", "adb")

    results = []
    for m in machines_cfg:
        ip   = m["ip"]
        name = m["name"]
        skip_acme = m.get("skip_acme", False)

        reachable = ping(ip, timeout=3)
        device_status = "Green" if reachable else "Red"
        acme_status   = "-"

        if not skip_acme and reachable:
            acme_status = get_acme_status(
                ip,
                acme_cfg.get("endpoint_template", "http://{ip}:8080/acme/status"),
                timeout=acme_cfg.get("timeout", 5),
            )

        entry = {
            "name":          name,
            "ip":            ip,
            "type":          m.get("type", "generic"),
            "reachable":     reachable,
            "acme_status":   acme_status,
            "device_status": device_status,
        }

        # Enrich iOS machines with macOS version via SSH
        if m.get("type") == "ios" and reachable:
            ssh = create_ssh_client(
                ip,
                ssh_cfg.get("username", ""),
                ssh_cfg.get("key_path", ""),
                ssh_cfg.get("password", ""),
                ssh_cfg.get("timeout", 10),
            )
            if ssh:
                macos_ver = get_macos_version(ssh)
                if macos_ver:
                    entry["macos_version"] = macos_ver
                ssh.close()

        results.append(entry)
    return results


def collect_device_counts(cfg: Dict[str, Any]) -> Dict[str, Any]:
    machines_cfg = cfg["machines"]
    ssh_cfg      = cfg.get("ssh", {})
    adb_cfg      = cfg.get("adb", {})
    adb_binary   = adb_cfg.get("binary", "adb")
    adb_port     = adb_cfg.get("remote_port", 5037)

    ios_total  = 0
    fos_total  = 0
    threep_total = 0

    for m in machines_cfg:
        if not ping(m["ip"], timeout=3):
            continue
        ssh = create_ssh_client(
            m["ip"],
            ssh_cfg.get("username", ""),
            ssh_cfg.get("key_path", ""),
            ssh_cfg.get("password", ""),
            ssh_cfg.get("timeout", 10),
        )
        if not ssh:
            continue

        if m.get("type") == "ios":
            ios_total += count_ios_devices_remote(ssh)
        elif m.get("type") == "android" and m.get("adb_host"):
            counts = count_android_devices_by_type_remote(ssh, adb_binary)
            fos_total   += counts["fos"]
            threep_total += counts["threep"]

        ssh.close()

    return {"ios": ios_total, "fos": fos_total, "threep": threep_total}


def collect_android_perf_status(cfg: Dict[str, Any]) -> Dict[str, str]:
    """
    Aggregates ADB reachability, battery, and Wi-Fi checks across all
    Android Perf machines. Returns overall Green/Red for each dimension.
    """
    machines_cfg = cfg["machines"]
    ssh_cfg      = cfg.get("ssh", {})
    adb_cfg      = cfg.get("adb", {})
    adb_binary   = adb_cfg.get("binary", "adb")

    android_machines = [m for m in machines_cfg if m.get("type") == "android" and m.get("adb_host")]

    adb_ok      = True
    battery_ok  = True
    wifi_ok     = True

    for m in android_machines:
        if not ping(m["ip"], timeout=3):
            adb_ok = False
            continue
        ssh = create_ssh_client(
            m["ip"],
            ssh_cfg.get("username", ""),
            ssh_cfg.get("key_path", ""),
            ssh_cfg.get("password", ""),
            ssh_cfg.get("timeout", 10),
        )
        if not ssh:
            adb_ok = False
            continue

        devices = {}
        raw_out = None
        try:
            from collectors.ssh_collector import run_remote_command
            raw_out = run_remote_command(ssh, f"{adb_binary} devices")
        except Exception:
            pass

        if raw_out:
            import re
            for line in raw_out.splitlines()[1:]:
                line = line.strip()
                if not line or line.startswith("*"):
                    continue
                parts = re.split(r"\s+", line, maxsplit=1)
                if len(parts) == 2:
                    devices[parts[0]] = parts[1]

        if not any(s == "device" for s in devices.values()):
            adb_ok = False
            battery_ok = False
            wifi_ok = False

        for serial, state in devices.items():
            if state != "device":
                continue
            batt = check_battery_via_ssh(ssh, serial, adb_binary)
            try:
                level = int(batt.replace("%", ""))
                battery_threshold = cfg.get("thresholds", {}).get("battery_min_percent", 80)
                if level < battery_threshold:
                    battery_ok = False
            except ValueError:
                pass

            if not check_wifi_disabled_via_ssh(ssh, serial, adb_binary):
                wifi_ok = False

        ssh.close()

    return {
        "adb_devices":  "Green" if adb_ok   else "Red",
        "battery":      "Green" if battery_ok else "Red",
        "wifi_disabled": "Green" if wifi_ok   else "Red",
    }



def collect_books_and_accounts(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Check books and accounts on all Android Perf devices.
    Returns dict keyed by machine name → serial → results.
    """
    machines_cfg = cfg["machines"]
    ssh_cfg = cfg.get("ssh", {})
    adb_cfg = cfg.get("adb", {})
    adb_binary = adb_cfg.get("binary", "adb")

    android_machines = [m for m in machines_cfg if m.get("type") == "android" and m.get("adb_host")]
    results = {}

    for m in android_machines:
        if not ping(m["ip"], timeout=3):
            continue
        ssh = create_ssh_client(
            m["ip"],
            ssh_cfg.get("username", ""),
            ssh_cfg.get("key_path", ""),
            ssh_cfg.get("password", ""),
            ssh_cfg.get("timeout", 10),
        )
        if not ssh:
            continue

        # Get connected device serials
        from collectors.ssh_collector import run_remote_command
        import re
        raw_out = run_remote_command(ssh, f"{adb_binary} devices")
        serials = []
        if raw_out:
            for line in raw_out.splitlines()[1:]:
                line = line.strip()
                if not line or line.startswith("*"):
                    continue
                parts = re.split(r"\s+", line, maxsplit=1)
                if len(parts) == 2 and parts[1] == "device":
                    serials.append(parts[0])

        if serials:
            results[m["name"]] = check_all_devices_books_and_accounts(ssh, serials, adb_binary)

        ssh.close()

    return results



def build_auto_callouts(machines: List[Dict[str, Any]], jenkins_data: Dict[str, Any] = None, thresholds: Dict[str, Any] = None,
                        kraft_status: Dict[str, Any] = None, books_accounts: Dict[str, Any] = None,
                        xcode_status: Dict[str, Any] = None) -> List[str]:
    """Generate automatic callout bullets from collected machine and Jenkins data."""
    callouts = []

    for m in machines:
        if not m["reachable"]:
            callouts.append(f"{m['name']} ({m['ip']}) is unreachable.")

        if m.get("macos_version"):
            ver = m["macos_version"]
            target = (thresholds or {}).get("macos_target_version", "15.7.7")
            if ver != target:
                callouts.append(
                    f"macOS update required to {target} on {m['name']} "
                    f"(currently {ver})."
                )

    # Jenkins node callouts
    if jenkins_data:
        for node in jenkins_data.get("nodes", []):
            if node["status"] == "Offline":
                callouts.append(f"Jenkins node '{node['name']}' is OFFLINE (unexpected).")
            elif node["status"] == "Disconnected":
                callouts.append(f"Jenkins node '{node['name']}' is disconnected (manually taken offline).")
        for job in jenkins_data.get("jobs", []):
            if job["status"] == "FAILURE":
                callouts.append(f"Jenkins job '{job['name']}' FAILED (build #{job.get('build_number', '?')}).")

    # KRAFT Device Farm callouts
    if kraft_status:
        for machine_name, status in kraft_status.items():
            if status.get("status") == "Red":
                offline_devs = status.get("offline_devices", [])
                callouts.append(
                    f"KRAFT: {machine_name} has {status.get('offline', 0)} device(s) offline"
                    f"{' — ' + ', '.join(offline_devs[:3]) if offline_devs else ''}."
                )
            elif status.get("status") == "auth_error":
                callouts.append(f"KRAFT: Authentication failed for {machine_name}. Check credentials.")

    # Books and account callouts
    if books_accounts:
        for machine_name, devices in books_accounts.items():
            for serial, checks in devices.items():
                book_info = checks.get("books", {})
                acct_info = checks.get("account", {})
                if book_info.get("status") == "Red":
                    for issue in book_info.get("issues", []):
                        callouts.append(f"Books: {machine_name}/{serial} — {issue}")
                if acct_info.get("status") == "Red":
                    callouts.append(
                        f"Account: {machine_name}/{serial} — Wrong account signed in: '{acct_info.get('account', 'unknown')}'"
                    )

    # Xcode/iOS callouts
    if xcode_status:
        for machine_name, status in xcode_status.items():
            if status.get("status") == "Red":
                for issue in status.get("issues", []):
                    callouts.append(f"iOS: {machine_name} — {issue}")
            elif status.get("status") == "Yellow":
                for issue in status.get("issues", []):
                    callouts.append(f"iOS Warning: {machine_name} — {issue}")

    return callouts




def collect_jenkins_status(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch Jenkins node statuses and optional job statuses."""
    jenkins_cfg = cfg.get("jenkins", {})
    if not jenkins_cfg or not jenkins_cfg.get("url"):
        return {"nodes": [], "jobs": []}

    import os
    url = jenkins_cfg["url"]
    user = jenkins_cfg.get("username") or os.environ.get("JENKINS_USER", "")
    token = jenkins_cfg.get("api_token") or os.environ.get("JENKINS_TOKEN", "")
    timeout = jenkins_cfg.get("timeout", 10)

    nodes = get_jenkins_nodes(url, user, token, timeout)
    jobs = []
    monitor_jobs = jenkins_cfg.get("monitor_jobs", [])
    if monitor_jobs:
        jobs = get_jenkins_job_status(url, monitor_jobs, user, token, timeout)

    return {"nodes": nodes, "jobs": jobs}


def run_report(config_path: str = "config.yaml", extra_callouts: List[str] = None):
    cfg = load_config(config_path)
    # Step 0: Discover current IPs (handles DHCP changes)
    discovery_cfg = cfg.get("discovery", {})
    if discovery_cfg.get("enabled"):
        print("[report] Running IP discovery...")
        discovered = discover_ips(cfg)
        if discovery_cfg.get("update_config"):
            changes = update_config_ips(config_path, discovered)
            if changes > 0:
                # Reload config with updated IPs
                with open(config_path) as f:
                    cfg = yaml.safe_load(f)
                print(f"[report] {changes} IP(s) updated in config.")

    print("[report] Collecting machine status...")
    machines = collect_machine_data(cfg)

    print("[report] Counting devices...")
    device_counts = collect_device_counts(cfg)

    print("[report] Checking Jenkins nodes...")
    jenkins_data = collect_jenkins_status(cfg)


    print("[report] Checking Android Perf status...")
    android_status = collect_android_perf_status(cfg)

    print("[report] Checking KRAFT Device Farm dashboard...")
    kraft_status = check_all_kraft_devices(cfg["machines"])

    print("[report] Checking books and accounts on Android devices...")
    books_accounts = collect_books_and_accounts(cfg)

    print("[report] Checking iOS Xcode device connectivity...")
    xcode_status = check_ios_machines(cfg["machines"], cfg.get("ssh", {}))

    callouts = build_auto_callouts(machines, jenkins_data, cfg.get("thresholds", {}),
                                    kraft_status, books_accounts, xcode_status)
    if extra_callouts:
        callouts.extend(extra_callouts)

    print("[report] Building HTML...")
    html = build_html(machines, device_counts, android_status, callouts, date.today(),
                      jenkins_nodes=jenkins_data.get("nodes", []),
                      jenkins_jobs=jenkins_data.get("jobs", []),
                      kraft_status=kraft_status,
                      books_accounts=books_accounts,
                      xcode_status=xcode_status)

    email_cfg = cfg["email"]
    subject   = email_cfg.get("subject", "Lab Maintenance Status Report")
    sender    = email_cfg.get("sender", "")
    recipients = email_cfg.get("recipients", [])

    if email_cfg.get("use_ses"):
        print("[report] Sending via AWS SES...")
        ok = send_via_ses(html, subject, sender, recipients)
    else:
        print("[report] Sending via SMTP...")
        ok = send_via_smtp(
            html, subject, sender, recipients,
            smtp_host=email_cfg.get("smtp_host", "smtp.gmail.com"),
            smtp_port=email_cfg.get("smtp_port", 587),
            use_tls=email_cfg.get("use_tls", True),
        )

    if ok:
        print("[report] Email sent successfully.")
    else:
        print("[report] Email failed. Check logs above.")
    return ok


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    run_report(config_path)
