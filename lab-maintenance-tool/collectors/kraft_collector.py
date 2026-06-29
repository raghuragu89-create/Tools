"""
KRAFT Device Farm Dashboard Collector
Checks device visibility and status on the KRAFT Device Farm web dashboard.
"""
import urllib3
import json
from typing import Dict, List, Any

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
http = urllib3.PoolManager(cert_reqs='CERT_NONE')

KRAFT_BASE_URL = "https://device-farm.example.com"


def check_kraft_devices(machine_name: str, jenkins_node: str, timeout: int = 10) -> Dict[str, Any]:
    """
    Query KRAFT Device Farm dashboard for devices associated with a machine.
    Returns device count, online/offline status, and any issues.
    """
    if not jenkins_node:
        return {"status": "skipped", "reason": "no jenkins_node configured", "devices": []}

    search_term = jenkins_node.replace("-nft-", "-")  # krq-android-nft-0 -> krq-android-0
    try:
        url = f"{KRAFT_BASE_URL}/api/v1/devices?search={search_term}&limit=50"
        resp = http.request('GET', url, timeout=timeout, headers={
            'Accept': 'application/json'
        })

        if resp.status == 200:
            data = json.loads(resp.data.decode('utf-8'))
            devices = data.get('devices', data.get('results', []))
            online = [d for d in devices if d.get('status', '').lower() == 'online']
            offline = [d for d in devices if d.get('status', '').lower() != 'online']

            return {
                "status": "Green" if len(offline) == 0 and len(online) > 0 else "Red",
                "total": len(devices),
                "online": len(online),
                "offline": len(offline),
                "offline_devices": [d.get('name', d.get('serial', 'unknown')) for d in offline],
                "search_term": search_term,
            }
        elif resp.status == 401 or resp.status == 403:
            return {"status": "auth_error", "reason": f"HTTP {resp.status} - authentication required"}
        else:
            return {"status": "error", "reason": f"HTTP {resp.status}"}

    except Exception as e:
        return {"status": "error", "reason": str(e)}


def check_all_kraft_devices(machines: List[Dict[str, Any]], timeout: int = 10) -> Dict[str, Dict[str, Any]]:
    """
    Check KRAFT status for all machines that have a jenkins_node configured.
    Returns dict keyed by machine name.
    """
    results = {}
    for machine in machines:
        name = machine.get('name', '')
        jenkins_node = machine.get('jenkins_node', '')
        if jenkins_node:
            results[name] = check_kraft_devices(name, jenkins_node, timeout)
    return results
