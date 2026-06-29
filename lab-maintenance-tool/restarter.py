"""
Weekly restart automation for lab devices and machines.
Restarts Android devices (via ADB) and optionally reboots host machines (via SSH).
Safety guards: checks if automations are running before restart.
"""
import time
import logging
from typing import Dict, List, Any

from collectors.ssh_collector import create_ssh_client, run_remote_command
from collectors.jenkins_collector import get_jenkins_nodes

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("restarter")


def is_automation_running(jenkins_cfg: Dict[str, Any]) -> bool:
    """Check if any Jenkins nodes are currently busy (automation running)."""
    if not jenkins_cfg or not jenkins_cfg.get("url"):
        return False
    import os
    url = jenkins_cfg["url"]
    user = jenkins_cfg.get("username") or os.environ.get("JENKINS_USER", "")
    token = jenkins_cfg.get("api_token") or os.environ.get("JENKINS_TOKEN", "")
    nodes = get_jenkins_nodes(url, user, token, timeout=10)
    busy_nodes = [n for n in nodes if not n.get("idle") and n["status"] == "Online"]
    if busy_nodes:
        log.warning(f"Automation running on: {[n['name'] for n in busy_nodes]}")
        return True
    return False


def restart_android_devices_via_ssh(
    ssh_client,
    adb_binary: str = "adb",
    wait_after: int = 30,
) -> Dict[str, str]:
    """
    Restart all connected Android devices on a host via SSH + ADB.
    Returns dict: {serial: "success"|"failed"}
    """
    results = {}

    # Get device list
    raw = run_remote_command(ssh_client, f"{adb_binary} devices")
    if not raw:
        log.error("Could not get device list")
        return results

    serials = []
    for line in raw.splitlines()[1:]:
        line = line.strip()
        if line and "\tdevice" in line:
            serial = line.split("\t")[0]
            serials.append(serial)

    if not serials:
        log.info("No devices connected — nothing to restart.")
        return results

    log.info(f"Found {len(serials)} devices to restart: {serials}")

    for serial in serials:
        log.info(f"  Restarting {serial}...")
        out = run_remote_command(ssh_client, f"{adb_binary} -s {serial} reboot")
        if out is not None:
            results[serial] = "success"
            log.info(f"    ✓ {serial} reboot command sent")
        else:
            results[serial] = "failed"
            log.error(f"    ✗ {serial} reboot failed")

    # Wait for devices to come back
    if serials:
        log.info(f"  Waiting {wait_after}s for devices to reboot...")
        time.sleep(wait_after)

        # Verify devices came back
        raw_after = run_remote_command(ssh_client, f"{adb_binary} devices")
        if raw_after:
            back_count = raw_after.count("\tdevice")
            log.info(f"  {back_count}/{len(serials)} devices back online")
        else:
            log.warning("  Could not verify device status after reboot")

    return results


def restart_machine_via_ssh(ssh_client, delay_seconds: int = 5) -> bool:
    """
    Reboot a remote machine via SSH.
    Sends 'sudo reboot' with a delay to allow SSH session to close.
    """
    log.info(f"  Sending reboot command (delay: {delay_seconds}s)...")
    cmd = f"sudo shutdown -r +{delay_seconds // 60 or 1}"
    try:
        run_remote_command(ssh_client, cmd)
        return True
    except Exception as e:
        log.error(f"  Reboot failed: {e}")
        return False


def run_weekly_restart(cfg: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """
    Execute weekly restart routine.
    - Checks if automations are running (aborts if yes)
    - Restarts Android devices on all Android Perf machines
    - Optionally reboots host machines (if restart.reboot_hosts is true)

    Returns summary dict.
    """
    restart_cfg = cfg.get("restart", {})
    ssh_cfg = cfg.get("ssh", {})
    adb_cfg = cfg.get("adb", {})
    jenkins_cfg = cfg.get("jenkins", {})
    adb_binary = adb_cfg.get("binary", "adb")

    log.info("=" * 50)
    log.info("WEEKLY RESTART ROUTINE")
    log.info("=" * 50)

    # Safety check: don't restart if automation is running
    if is_automation_running(jenkins_cfg):
        log.error("ABORTED: Automation currently running. Will retry next cycle.")
        return {"status": "aborted", "reason": "automation_running"}

    if dry_run:
        log.info("[DRY RUN] Would restart devices but not executing.")
        return {"status": "dry_run"}

    machines_cfg = cfg.get("machines", [])
    android_machines = [m for m in machines_cfg if m.get("type") == "android" and m.get("adb_host")]
    reboot_hosts = restart_cfg.get("reboot_hosts", False)

    summary = {"devices_restarted": 0, "devices_failed": 0, "hosts_rebooted": 0, "machines_processed": []}

    for m in android_machines:
        ip = m["ip"]
        name = m["name"]
        log.info(f"\n--- {name} ({ip}) ---")

        ssh = create_ssh_client(
            ip,
            ssh_cfg.get("username", ""),
            ssh_cfg.get("key_path", ""),
            ssh_cfg.get("password", ""),
            ssh_cfg.get("timeout", 10),
        )
        if not ssh:
            log.error(f"  Cannot SSH to {name} — skipping")
            summary["machines_processed"].append({"name": name, "status": "ssh_failed"})
            continue

        # Restart devices
        results = restart_android_devices_via_ssh(ssh, adb_binary, wait_after=restart_cfg.get("wait_after_reboot", 30))
        success_count = sum(1 for v in results.values() if v == "success")
        fail_count = sum(1 for v in results.values() if v == "failed")
        summary["devices_restarted"] += success_count
        summary["devices_failed"] += fail_count

        # Optionally reboot the host machine itself
        if reboot_hosts:
            log.info(f"  Rebooting host {name}...")
            if restart_machine_via_ssh(ssh, delay_seconds=60):
                summary["hosts_rebooted"] += 1

        ssh.close()
        summary["machines_processed"].append({
            "name": name,
            "devices_restarted": success_count,
            "devices_failed": fail_count,
        })

    log.info("\n" + "=" * 50)
    log.info(f"RESTART COMPLETE: {summary['devices_restarted']} devices restarted, "
             f"{summary['devices_failed']} failed, {summary['hosts_rebooted']} hosts rebooted")
    log.info("=" * 50)

    summary["status"] = "completed"
    return summary


if __name__ == "__main__":
    import sys
    import yaml

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    dry = "--dry-run" in sys.argv
    run_weekly_restart(cfg, dry_run=dry)
