"""
iOS Xcode Device Connectivity Collector
Verifies iOS device pairing and connection status through Xcode CLI tools.
"""
from typing import Dict, List, Any


def check_xcode_devices(ssh_client) -> Dict[str, Any]:
    """
    Check iOS device connectivity via Xcode's xcdevice/xcrun tools.
    Returns list of connected devices with pairing status.
    """
    from collectors.ssh_collector import run_remote_command

    result = {
        "devices": [],
        "total": 0,
        "connected": 0,
        "issues": [],
        "status": "unknown"
    }

    try:
        # Method 1: Use xcrun xctrace to list devices
        cmd = 'xcrun xctrace list devices 2>/dev/null | grep -v "Simulator"'
        out = run_remote_command(ssh_client, cmd)

        if out:
            for line in out.splitlines():
                line = line.strip()
                if not line or line.startswith("==") or "Simulator" in line:
                    continue
                # Format: "Device Name (OS Version) (UDID)"
                if "(" in line:
                    device_info = {
                        "name": line.split("(")[0].strip(),
                        "raw": line,
                        "status": "connected",
                        "warning": False
                    }
                    result["devices"].append(device_info)

        # Method 2: Fallback - use system_profiler
        if not result["devices"]:
            cmd2 = 'system_profiler SPUSBDataType 2>/dev/null | grep -A2 "iPhone\\|iPad"'
            out2 = run_remote_command(ssh_client, cmd2)
            if out2:
                for line in out2.splitlines():
                    if "iPhone" in line or "iPad" in line:
                        result["devices"].append({
                            "name": line.strip().rstrip(":"),
                            "raw": line.strip(),
                            "status": "connected",
                            "warning": False
                        })

        # Method 3: Use cfgutil for managed devices
        cmd3 = 'cfgutil list 2>/dev/null'
        out3 = run_remote_command(ssh_client, cmd3)
        if out3 and "ECID" in out3:
            # cfgutil found devices - parse count
            device_lines = [l for l in out3.splitlines() if l.strip() and "ECID" in l]
            if len(device_lines) > len(result["devices"]):
                for line in device_lines:
                    if not any(line.strip() in d.get("raw", "") for d in result["devices"]):
                        result["devices"].append({
                            "name": line.strip(),
                            "raw": line.strip(),
                            "status": "connected",
                            "warning": False
                        })

        # Check for pairing issues via devicectl (Xcode 15+)
        cmd4 = 'xcrun devicectl list devices 2>/dev/null'
        out4 = run_remote_command(ssh_client, cmd4)
        if out4:
            for line in out4.splitlines():
                line_lower = line.lower()
                if "error" in line_lower or "unpaired" in line_lower or "disconnected" in line_lower:
                    result["issues"].append(line.strip())
                    # Mark matching device as warning
                    for d in result["devices"]:
                        if any(part in line for part in d.get("name", "").split()):
                            d["warning"] = True
                            d["status"] = "warning"

        # Summarize
        result["total"] = len(result["devices"])
        result["connected"] = len([d for d in result["devices"] if d["status"] == "connected"])

        if result["total"] == 0:
            result["status"] = "Red"
            result["issues"].append("No iOS devices detected via Xcode")
        elif result["issues"]:
            result["status"] = "Yellow"
        else:
            result["status"] = "Green"

    except Exception as e:
        result["status"] = "error"
        result["issues"].append(f"Xcode check failed: {str(e)}")

    return result


def check_ios_machines(machines: List[Dict[str, Any]], ssh_cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Check Xcode device connectivity for all iOS machines.
    Returns dict keyed by machine name.
    """
    from collectors.ssh_collector import create_ssh_client
    from collectors.ping_collector import ping

    results = {}
    ios_machines = [m for m in machines if m.get("type") == "ios"]

    for m in ios_machines:
        name = m.get("name", "")
        ip = m.get("ip", "")

        if not ping(ip, timeout=3):
            results[name] = {"status": "Red", "issues": ["Machine unreachable"], "devices": [], "total": 0, "connected": 0}
            continue

        ssh = create_ssh_client(
            ip,
            ssh_cfg.get("username", ""),
            ssh_cfg.get("key_path", ""),
            ssh_cfg.get("password", ""),
            ssh_cfg.get("timeout", 10),
        )

        if not ssh:
            results[name] = {"status": "Red", "issues": ["SSH connection failed"], "devices": [], "total": 0, "connected": 0}
            continue

        results[name] = check_xcode_devices(ssh)
        ssh.close()

    return results
