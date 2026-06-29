import os
from typing import Optional

try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False


def create_ssh_client(host: str, username: str, key_path: str = "", password: str = "", timeout: int = 10):
    """
    Returns a connected paramiko SSHClient or None on failure.
    Tries key-based auth first, falls back to password.
    """
    if not PARAMIKO_AVAILABLE:
        return None

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    key_path = os.path.expanduser(key_path) if key_path else ""
    ssh_pass = password or os.environ.get("SSH_PASS", "")

    try:
        if key_path and os.path.exists(key_path):
            client.connect(host, username=username, key_filename=key_path, timeout=timeout)
        elif ssh_pass:
            client.connect(host, username=username, password=ssh_pass, timeout=timeout)
        else:
            client.connect(host, username=username, timeout=timeout)
        return client
    except Exception:
        return None


def run_remote_command(ssh_client, command: str, timeout: int = 15) -> Optional[str]:
    """Run a shell command over SSH and return stdout, or None on error."""
    if ssh_client is None:
        return None
    try:
        _, stdout, _ = ssh_client.exec_command(command, timeout=timeout)
        return stdout.read().decode().strip()
    except Exception:
        return None


def get_macos_version(ssh_client) -> Optional[str]:
    """Return macOS version string, e.g. '15.6.1'"""
    return run_remote_command(ssh_client, "sw_vers -productVersion")


def get_adb_devices_remote(ssh_client, adb_binary: str = "adb") -> Optional[str]:
    """Return raw output of `adb devices` from a remote machine."""
    return run_remote_command(ssh_client, f"{adb_binary} devices")
