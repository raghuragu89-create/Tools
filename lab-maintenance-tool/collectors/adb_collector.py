import subprocess
import re
from typing import Dict


def get_local_devices(adb_binary: str = "adb") -> Dict[str, str]:
    """Run adb devices locally and return {serial: state} map."""
    try:
        result = subprocess.run(
            [adb_binary, "devices"],
            capture_output=True, text=True, timeout=15
        )
        return _parse_adb_output(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}


def get_remote_devices(host: str, port: int = 5037, adb_binary: str = "adb") -> Dict[str, str]:
    """Connect to a remote adb server and list devices."""
    try:
        subprocess.run(
            [adb_binary, "-H", host, "-P", str(port), "connect", f"{host}:{port}"],
            capture_output=True, timeout=10
        )
        result = subprocess.run(
            [adb_binary, "-H", host, "-P", str(port), "devices"],
            capture_output=True, text=True, timeout=15
        )
        return _parse_adb_output(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}


def _parse_adb_output(output: str) -> Dict[str, str]:
    devices = {}
    for line in output.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = re.split(r"\s+", line, maxsplit=1)
        if len(parts) == 2:
            serial, state = parts
            devices[serial] = state
    return devices


def count_connected(devices: Dict[str, str]) -> int:
    return sum(1 for state in devices.values() if state == "device")


def check_wifi_disabled_via_ssh(ssh_client, device_serial: str, adb_binary: str = "adb") -> bool:
    """
    SSH into an adb host and check if Wi-Fi is disabled on a device.
    Returns True if Wi-Fi is disabled.
    """
    cmd = f"{adb_binary} -s {device_serial} shell dumpsys wifi | grep 'Wi-Fi is'"
    stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=15)
    output = stdout.read().decode().strip().lower()
    return "disabled" in output or "not enabled" in output


def check_battery_via_ssh(ssh_client, device_serial: str, adb_binary: str = "adb") -> str:
    """Returns battery level string from a remote adb host."""
    cmd = f"{adb_binary} -s {device_serial} shell dumpsys battery | grep level"
    stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=15)
    output = stdout.read().decode().strip()
    match = re.search(r"level:\s*(\d+)", output)
    return f"{match.group(1)}%" if match else "Unknown"
