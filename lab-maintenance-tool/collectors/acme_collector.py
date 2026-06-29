import urllib.request
import json


def get_acme_status(ip: str, endpoint_template: str, timeout: int = 5) -> str:
    """
    Fetch ACME status from a machine.
    Returns 'Green', 'Red', or 'Unknown'.
    Adapt endpoint_template and JSON key to match your actual ACME API.
    """
    url = endpoint_template.format(ip=ip)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            status = data.get("status", "Unknown")
            return _normalize(status)
    except Exception:
        return "Unknown"


def _normalize(status: str) -> str:
    s = status.strip().lower()
    if s in ("green", "ok", "healthy", "up"):
        return "Green"
    if s in ("red", "error", "unhealthy", "down", "critical"):
        return "Red"
    return "Unknown"
