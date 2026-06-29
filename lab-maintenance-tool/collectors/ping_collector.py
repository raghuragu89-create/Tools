import platform
import subprocess


def ping(ip: str, timeout: int = 3) -> bool:
    """Ping an IP address. Returns True if reachable."""
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(timeout), ip]

    try:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout + 2)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
