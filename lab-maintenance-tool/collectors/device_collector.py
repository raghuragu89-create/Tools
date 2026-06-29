"""
Aggregate collector: gathers all device counts by type using SSH + adb.
Counts: iOS (via `idevice_id -l` or `cfgutil`), FOS, 3P Android.
"""
import re
from typing import Dict
from collectors.ssh_collector import run_remote_command


_FOS_SERIAL_PATTERN = re.compile(r"^(B0|G0|A0)", re.IGNORECASE)  # adjust to your FOS serial prefix


def count_ios_devices_remote(ssh_client) -> int:
    """Count connected iOS devices via idevice_id on a remote Mac."""
    out = run_remote_command(ssh_client, "idevice_id -l 2>/dev/null | grep -c .")
    try:
        return int(out.strip())
    except (TypeError, ValueError):
        return 0


def count_android_devices_by_type_remote(ssh_client, adb_binary: str = "adb") -> Dict[str, int]:
    """
    SSH into an Android host and split device list into FOS vs 3P.
    Returns dict with keys 'fos', 'threep'.
    """
    out = run_remote_command(ssh_client, f"{adb_binary} devices")
    if not out:
        return {"fos": 0, "threep": 0}

    fos, threep = 0, 0
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = re.split(r"\s+", line, maxsplit=1)
        if len(parts) == 2 and parts[1].strip() == "device":
            serial = parts[0]
            if _FOS_SERIAL_PATTERN.match(serial):
                fos += 1
            else:
                threep += 1
    return {"fos": fos, "threep": threep}
