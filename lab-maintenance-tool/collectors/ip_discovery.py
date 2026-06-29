"""
IP Discovery Collector — Detects current IP addresses for lab machines daily.
Handles DHCP environments where IPs change frequently.

Strategies (tried in order):
1. Hostname resolution (DNS/mDNS) — if machine has a hostname
2. ARP table lookup — find by MAC address
3. Network scan (ping sweep) + SSH fingerprint matching
4. Jenkins node API — Jenkins tracks agent IPs
"""
import subprocess
import socket
import re
import json
import os
import logging
from typing import Dict, List, Optional, Any

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ip_discovery")


def resolve_hostname(hostname: str) -> Optional[str]:
    """Try DNS resolution for a hostname."""
    try:
        ip = socket.gethostbyname(hostname)
        return ip
    except socket.gaierror:
        return None


def get_arp_table() -> Dict[str, str]:
    """
    Parse ARP table to get MAC→IP mapping.
    Returns: {mac_address: ip_address}
    """
    mac_to_ip = {}
    try:
        if os.name == "nt":
            result = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10)
        else:
            result = subprocess.run(["arp", "-an"], capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            return mac_to_ip

        for line in result.stdout.splitlines():
            # Windows: 10.0.0.1  00-1a-2b-3c-4d-5e  dynamic
            # Linux/Mac: ? (10.0.0.1) at 00:1a:2b:3c:4d:5e [ether] on eth0
            if os.name == "nt":
                parts = line.split()
                if len(parts) >= 3:
                    ip_match = re.match(r'(\d+\.\d+\.\d+\.\d+)', parts[0].strip())
                    mac_match = re.match(r'([0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2})', parts[1].strip())
                    if ip_match and mac_match:
                        mac = mac_match.group(1).replace("-", ":").lower()
                        mac_to_ip[mac] = ip_match.group(1)
            else:
                m = re.search(r'\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)', line)
                if m:
                    mac_to_ip[m.group(2).lower()] = m.group(1)

    except Exception as e:
        log.warning(f"ARP table fetch failed: {e}")

    return mac_to_ip


def ping_sweep(subnet: str, timeout_ms: int = 200) -> List[str]:
    """
    Quick ping sweep of a /24 subnet to populate ARP table.
    Returns list of responding IPs.
    """
    alive = []
    # Use OS-specific fast ping
    if os.name == "nt":
        # Windows: use ping with very short timeout
        for i in range(1, 255):
            ip = f"{subnet}.{i}"
            try:
                result = subprocess.run(
                    ["ping", "-n", "1", "-w", str(timeout_ms), ip],
                    capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    alive.append(ip)
            except Exception:
                pass
    else:
        # Unix: parallel ping with fping if available, else sequential
        try:
            result = subprocess.run(
                ["fping", "-a", "-g", f"{subnet}.1", f"{subnet}.254", "-t", str(timeout_ms)],
                capture_output=True, text=True, timeout=60
            )
            alive = [ip.strip() for ip in result.stdout.splitlines() if ip.strip()]
        except FileNotFoundError:
            # Fallback: sequential ping (slower)
            for i in range(1, 255):
                ip = f"{subnet}.{i}"
                try:
                    result = subprocess.run(
                        ["ping", "-c", "1", "-W", "1", ip],
                        capture_output=True, text=True, timeout=2
                    )
                    if result.returncode == 0:
                        alive.append(ip)
                except Exception:
                    pass

    return alive


def discover_ip_by_mac(mac_address: str, subnet: str = None) -> Optional[str]:
    """Find current IP for a known MAC address."""
    # First check existing ARP table
    arp = get_arp_table()
    mac_lower = mac_address.lower().replace("-", ":")
    if mac_lower in arp:
        return arp[mac_lower]

    # If subnet provided, do a ping sweep to refresh ARP table
    if subnet:
        log.info(f"  Ping sweeping {subnet}.0/24 to find {mac_address}...")
        ping_sweep(subnet)
        # Re-check ARP after sweep
        arp = get_arp_table()
        if mac_lower in arp:
            return arp[mac_lower]

    return None


def discover_ip_from_jenkins(
    jenkins_url: str,
    node_name: str,
    username: str = "",
    api_token: str = "",
) -> Optional[str]:
    """Get a node's IP from Jenkins computer API."""
    import urllib.request
    import base64

    url = f"{jenkins_url.rstrip('/')}/computer/{node_name}/api/json?tree=offline,offlineCause,temporaryOfflineCause"
    # Jenkins doesn't directly expose IP in standard API, but the launch log does
    # Try the agent log instead
    log_url = f"{jenkins_url.rstrip('/')}/computer/{node_name}/logText/progressiveText?start=0"

    req = urllib.request.Request(log_url)
    if username and api_token:
        creds = base64.b64encode(f"{username}:{api_token}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            log_text = resp.read().decode(errors="replace")
        # Look for IP in connection log
        # Common patterns: "Agent connected from /10.0.0.1" or "Remoting version: ... [10.0.0.1]"
        m = re.search(r'(\d+\.\d+\.\d+\.\d+)', log_text)
        if m:
            return m.group(1)
    except Exception:
        pass

    return None


def discover_ips(cfg: Dict[str, Any]) -> Dict[str, str]:
    """
    Main discovery function. Attempts to find current IPs for all machines.
    Returns: {machine_name: discovered_ip}

    Strategy per machine:
    1. If hostname defined → DNS resolve
    2. If mac_address defined → ARP lookup (with optional ping sweep)
    3. If jenkins_node defined → Jenkins log parsing
    4. Fallback: use configured static IP and verify with ping
    """
    machines = cfg.get("machines", [])
    jenkins_cfg = cfg.get("jenkins", {})
    discovery_cfg = cfg.get("discovery", {})
    subnet = discovery_cfg.get("subnet", "")  # e.g., "10.0.0"

    discovered = {}

    log.info("=" * 50)
    log.info("IP DISCOVERY — Finding current machine addresses")
    log.info("=" * 50)

    for m in machines:
        name = m["name"]
        static_ip = m.get("ip", "")
        hostname = m.get("hostname", "")
        mac = m.get("mac_address", "")
        jenkins_node = m.get("jenkins_node", "")

        new_ip = None

        # Strategy 1: Hostname resolution
        if hostname:
            new_ip = resolve_hostname(hostname)
            if new_ip:
                log.info(f"  {name}: resolved via hostname → {new_ip}")

        # Strategy 2: MAC address lookup
        if not new_ip and mac:
            new_ip = discover_ip_by_mac(mac, subnet)
            if new_ip:
                log.info(f"  {name}: found via MAC {mac} → {new_ip}")

        # Strategy 3: Jenkins node log
        if not new_ip and jenkins_node and jenkins_cfg.get("url"):
            new_ip = discover_ip_from_jenkins(
                jenkins_cfg["url"], jenkins_node,
                jenkins_cfg.get("username", ""),
                jenkins_cfg.get("api_token", "")
            )
            if new_ip:
                log.info(f"  {name}: found via Jenkins node '{jenkins_node}' → {new_ip}")

        # Strategy 4: Verify static IP with ping
        if not new_ip:
            from collectors.ping_collector import ping
            if ping(static_ip):
                new_ip = static_ip
                log.info(f"  {name}: static IP {static_ip} still reachable ✓")
            else:
                log.warning(f"  {name}: static IP {static_ip} UNREACHABLE — could not discover new IP")
                new_ip = static_ip  # Keep old IP, report will show it as unreachable

        discovered[name] = new_ip

    return discovered


def update_config_ips(config_path: str, discovered: Dict[str, str]) -> int:
    """
    Update config.yaml with newly discovered IPs.
    Returns number of IPs changed.
    """
    try:
        import yaml
    except ImportError:
        log.error("PyYAML required for config update")
        return 0

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    changes = 0
    for m in cfg.get("machines", []):
        name = m["name"]
        if name in discovered and discovered[name] != m.get("ip"):
            old_ip = m.get("ip", "?")
            new_ip = discovered[name]
            log.info(f"  IP CHANGED: {name}: {old_ip} → {new_ip}")
            m["ip"] = new_ip
            changes += 1

    if changes > 0:
        with open(config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
        log.info(f"\n  Updated {changes} IP(s) in {config_path}")

        # Also save history for audit
        history_path = os.path.join(os.path.dirname(config_path), ".ip_history.json")
        history = []
        if os.path.exists(history_path):
            try:
                with open(history_path) as f:
                    history = json.load(f)
            except Exception:
                pass
        from datetime import datetime, timezone
        history.append({
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "changes": {name: discovered[name] for name in discovered
                        if any(m["name"] == name and m.get("ip") != discovered[name]
                               for m in cfg.get("machines", []))}
        })
        # Keep last 90 days of history
        history = history[-90:]
        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
    else:
        log.info("\n  No IP changes detected.")

    return changes


if __name__ == "__main__":
    import sys
    try:
        import yaml
    except ImportError:
        print("PyYAML required: pip install pyyaml")
        sys.exit(1)

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    discovered = discover_ips(cfg)
    print(f"\nDiscovered IPs: {json.dumps(discovered, indent=2)}")

    if "--update" in sys.argv:
        changes = update_config_ips(config_path, discovered)
        print(f"\n{changes} IP(s) updated in config.")
