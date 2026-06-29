"""
Jenkins node/agent status collector.
Queries Jenkins REST API to check which nodes are online/offline.
"""
import json
import urllib.request
import urllib.error
import base64
from typing import Dict, List, Optional


def get_jenkins_nodes(
    jenkins_url: str,
    username: str = "",
    api_token: str = "",
    timeout: int = 10,
) -> List[Dict[str, str]]:
    """
    Fetch all Jenkins agent/node statuses.
    Returns list of dicts: [{"name": "node-1", "status": "Online|Offline|Disconnected", "idle": True/False}]
    """
    url = f"{jenkins_url.rstrip('/')}/computer/api/json?tree=computer[displayName,offline,idle,temporarilyOffline]"

    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")

    # Basic auth if credentials provided
    if username and api_token:
        creds = base64.b64encode(f"{username}:{api_token}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[jenkins] HTTP error {e.code}: {e.reason}")
        return []
    except urllib.error.URLError as e:
        print(f"[jenkins] Connection error: {e.reason}")
        return []
    except Exception as e:
        print(f"[jenkins] Unexpected error: {e}")
        return []

    nodes = []
    for computer in data.get("computer", []):
        name = computer.get("displayName", "Unknown")
        offline = computer.get("offline", False)
        temp_offline = computer.get("temporarilyOffline", False)
        idle = computer.get("idle", True)

        if offline and temp_offline:
            status = "Disconnected"  # Manually taken offline
        elif offline:
            status = "Offline"       # Unexpectedly offline
        else:
            status = "Online"

        nodes.append({
            "name": name,
            "status": status,
            "idle": idle,
        })

    return nodes


def get_jenkins_job_status(
    jenkins_url: str,
    job_names: List[str],
    username: str = "",
    api_token: str = "",
    timeout: int = 10,
) -> List[Dict[str, str]]:
    """
    Fetch last build status for specific Jenkins jobs.
    Returns: [{"name": "job-1", "status": "SUCCESS|FAILURE|UNSTABLE|RUNNING", "url": "..."}]
    """
    results = []
    for job_name in job_names:
        url = f"{jenkins_url.rstrip('/')}/job/{job_name}/lastBuild/api/json?tree=result,number,url,building"

        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        if username and api_token:
            creds = base64.b64encode(f"{username}:{api_token}".encode()).decode()
            req.add_header("Authorization", f"Basic {creds}")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            building = data.get("building", False)
            result = data.get("result", "UNKNOWN")
            status = "RUNNING" if building else (result or "UNKNOWN")
            results.append({
                "name": job_name,
                "status": status,
                "build_number": data.get("number", 0),
                "url": data.get("url", ""),
            })
        except Exception as e:
            results.append({
                "name": job_name,
                "status": "UNREACHABLE",
                "build_number": 0,
                "url": "",
            })

    return results


def summarize_nodes(nodes: List[Dict[str, str]]) -> Dict[str, int]:
    """Return counts by status."""
    summary = {"Online": 0, "Offline": 0, "Disconnected": 0}
    for n in nodes:
        status = n["status"]
        summary[status] = summary.get(status, 0) + 1
    return summary
