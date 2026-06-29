"""
Builds the HTML email body from collected lab data.
"""
from datetime import date
from typing import Any, Dict, List


_STATUS_COLOR = {
    "Green": "#2e7d32",
    "Red":   "#c62828",
    "Unknown": "#616161",
    "-": "#9e9e9e",
}

_STATUS_BG = {
    "Green": "#e8f5e9",
    "Red":   "#ffebee",
    "Unknown": "#f5f5f5",
    "-": "#fafafa",
}


def _badge(status: str) -> str:
    color = _STATUS_COLOR.get(status, "#616161")
    bg = _STATUS_BG.get(status, "#f5f5f5")
    return (
        f'<span style="background:{bg};color:{color};padding:2px 10px;'
        f'border-radius:12px;font-weight:bold;font-size:13px;">{status}</span>'
    )


def _machine_rows(machines: List[Dict[str, Any]]) -> str:
    rows = []
    for m in machines:
        acme = m.get("acme_status", "-")
        device = m.get("device_status", "-")
        rows.append(
            f"<tr>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee'>{m['name']}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee'>{m['ip']}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{_badge(acme)}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{_badge(device)}</td>"
            f"</tr>"
        )
    return "".join(rows)


def _device_rows(device_counts: Dict[str, Any]) -> str:
    rows = []
    items = [
        ("iOS", device_counts.get("ios", 0)),
        ("FOS", device_counts.get("fos", 0)),
        ("3P",  device_counts.get("threep", 0)),
    ]
    for label, count in items:
        rows.append(
            f"<tr>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee'>{label}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee'>{count} devices connected</td>"
            f"</tr>"
        )
    total = sum(c for _, c in items)
    rows.append(
        f"<tr style='font-weight:bold;background:#f9fbe7'>"
        f"<td style='padding:8px 12px' colspan='2'>Total No of devices connected: {total}</td>"
        f"</tr>"
    )
    return "".join(rows)


def _android_status_rows(android_status: Dict[str, str]) -> str:
    rows = []
    items = [
        ("ADB devices", android_status.get("adb_devices", "Unknown")),
        ("Battery Status", android_status.get("battery", "Unknown")),
        ("Device WIFI disable", android_status.get("wifi_disabled", "Unknown")),
    ]
    for label, status in items:
        rows.append(
            f"<tr>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee'>{label}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{_badge(status)}</td>"
            f"</tr>"
        )
    return "".join(rows)


def _callout_items(callouts: List[str]) -> str:
    if not callouts:
        return "<li>No callouts today.</li>"
    return "".join(f"<li style='margin-bottom:6px'>{c}</li>" for c in callouts)



def _jenkins_section(jenkins_nodes: List[Dict[str, str]], jenkins_jobs: List[Dict[str, str]]) -> str:
    """Build Jenkins nodes + jobs HTML section."""
    if not jenkins_nodes and not jenkins_jobs:
        return ""

    node_status_map = {"Online": "Green", "Offline": "Red", "Disconnected": "Unknown"}
    job_status_map = {"SUCCESS": "Green", "FAILURE": "Red", "UNSTABLE": "Unknown",
                      "RUNNING": "Green", "UNREACHABLE": "Red", "UNKNOWN": "Unknown"}

    html = '<h3 style="color:#1565c0">Jenkins Nodes</h3>'
    if jenkins_nodes:
        html += '<table style="border-collapse:collapse;width:70%;margin-bottom:24px">'
        html += '<thead><tr style="background:#1565c0;color:white">'
        html += '<th style="padding:10px 12px;text-align:left">Node Name</th>'
        html += '<th style="padding:10px 12px;text-align:center">Status</th>'
        html += '<th style="padding:10px 12px;text-align:center">Idle</th>'
        html += '</tr></thead><tbody>'
        for node in jenkins_nodes:
            status_key = node_status_map.get(node["status"], "Unknown")
            idle_txt = "Yes" if node.get("idle") else "Busy"
            html += (f"<tr>"
                     f"<td style='padding:8px 12px;border-bottom:1px solid #eee'>{node['name']}</td>"
                     f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{_badge(status_key)}</td>"
                     f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{idle_txt}</td>"
                     f"</tr>")
        html += '</tbody></table>'

    if jenkins_jobs:
        html += '<h3 style="color:#1565c0">Jenkins Jobs (Last Build)</h3>'
        html += '<table style="border-collapse:collapse;width:70%;margin-bottom:24px">'
        html += '<thead><tr style="background:#1565c0;color:white">'
        html += '<th style="padding:10px 12px;text-align:left">Job Name</th>'
        html += '<th style="padding:10px 12px;text-align:center">Status</th>'
        html += '<th style="padding:10px 12px;text-align:center">Build #</th>'
        html += '</tr></thead><tbody>'
        for job in jenkins_jobs:
            status_key = job_status_map.get(job["status"], "Unknown")
            html += (f"<tr>"
                     f"<td style='padding:8px 12px;border-bottom:1px solid #eee'>{job['name']}</td>"
                     f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{_badge(status_key)}</td>"
                     f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>#{job.get('build_number', '?')}</td>"
                     f"</tr>")
        html += '</tbody></table>'

    return html



def _kraft_section(kraft_status: Dict[str, Any]) -> str:
    if not kraft_status:
        return ""
    html = '<h3 style="color:#1565c0">KRAFT Device Farm Status</h3>'
    html += '<table style="border-collapse:collapse;width:70%;margin-bottom:24px">'
    html += '<thead><tr style="background:#1565c0;color:white">'
    html += '<th style="padding:10px 12px;text-align:left">Machine</th>'
    html += '<th style="padding:10px 12px;text-align:center">Online</th>'
    html += '<th style="padding:10px 12px;text-align:center">Offline</th>'
    html += '<th style="padding:10px 12px;text-align:center">Status</th>'
    html += '</tr></thead><tbody>'
    for name, info in kraft_status.items():
        status = info.get("status", "Unknown")
        online = info.get("online", 0)
        offline = info.get("offline", 0)
        html += (f"<tr>"
                 f"<td style='padding:8px 12px;border-bottom:1px solid #eee'>{name}</td>"
                 f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{online}</td>"
                 f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{offline}</td>"
                 f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{_badge(status)}</td>"
                 f"</tr>")
    html += '</tbody></table>'
    return html


def _books_accounts_section(books_accounts: Dict[str, Any]) -> str:
    if not books_accounts:
        return ""
    html = '<h3 style="color:#1565c0">Books &amp; Account Status</h3>'
    html += '<table style="border-collapse:collapse;width:80%;margin-bottom:24px">'
    html += '<thead><tr style="background:#1565c0;color:white">'
    html += '<th style="padding:10px 12px;text-align:left">Machine</th>'
    html += '<th style="padding:10px 12px;text-align:left">Device</th>'
    html += '<th style="padding:10px 12px;text-align:center">Books</th>'
    html += '<th style="padding:10px 12px;text-align:center">Account</th>'
    html += '</tr></thead><tbody>'
    for machine_name, devices in books_accounts.items():
        for serial, checks in devices.items():
            book_info = checks.get("books", {})
            acct_info = checks.get("account", {})
            book_status = book_info.get("status", "Unknown")
            acct_status = acct_info.get("status", "Unknown")
            book_text = f"{book_info.get('books_downloaded', '?')}/10"
            html += (f"<tr>"
                     f"<td style='padding:8px 12px;border-bottom:1px solid #eee'>{machine_name}</td>"
                     f"<td style='padding:8px 12px;border-bottom:1px solid #eee;font-size:12px'>{serial[:16]}</td>"
                     f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{_badge(book_status)} {book_text}</td>"
                     f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{_badge(acct_status)}</td>"
                     f"</tr>")
    html += '</tbody></table>'
    return html


def _xcode_section(xcode_status: Dict[str, Any]) -> str:
    if not xcode_status:
        return ""
    html = '<h3 style="color:#1565c0">iOS Xcode Device Connectivity</h3>'
    html += '<table style="border-collapse:collapse;width:70%;margin-bottom:24px">'
    html += '<thead><tr style="background:#1565c0;color:white">'
    html += '<th style="padding:10px 12px;text-align:left">Machine</th>'
    html += '<th style="padding:10px 12px;text-align:center">Devices</th>'
    html += '<th style="padding:10px 12px;text-align:center">Status</th>'
    html += '</tr></thead><tbody>'
    for name, info in xcode_status.items():
        status = info.get("status", "Unknown")
        total = info.get("total", 0)
        connected = info.get("connected", 0)
        html += (f"<tr>"
                 f"<td style='padding:8px 12px;border-bottom:1px solid #eee'>{name}</td>"
                 f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{connected}/{total}</td>"
                 f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center'>{_badge(status)}</td>"
                 f"</tr>")
    html += '</tbody></table>'
    return html


def build_html(
    machines: List[Dict[str, Any]],
    device_counts: Dict[str, Any],
    android_status: Dict[str, str],
    callouts: List[str],
    report_date: date = None,
    jenkins_nodes: List[Dict[str, str]] = None,
    jenkins_jobs: List[Dict[str, str]] = None,
    kraft_status: Dict[str, Any] = None,
    books_accounts: Dict[str, Any] = None,
    xcode_status: Dict[str, Any] = None,
) -> str:
    report_date = report_date or date.today()
    date_str = report_date.strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;color:#333;max-width:800px;margin:auto;padding:20px">

  <h2 style="color:#1565c0;border-bottom:2px solid #1565c0;padding-bottom:8px">
    Lab Maintenance Status Report — YJR Devices
  </h2>
  <p style="color:#666">Generated: {date_str}</p>

  <h3 style="color:#1565c0">Callouts</h3>
  <ul style="line-height:1.8">
    {_callout_items(callouts)}
  </ul>

  <h3 style="color:#1565c0">Machine Status</h3>
  <table style="border-collapse:collapse;width:100%;margin-bottom:24px">
    <thead>
      <tr style="background:#1565c0;color:white">
        <th style="padding:10px 12px;text-align:left">Machine Name</th>
        <th style="padding:10px 12px;text-align:left">IP Address</th>
        <th style="padding:10px 12px;text-align:center">ACME Status</th>
        <th style="padding:10px 12px;text-align:center">Device Status</th>
      </tr>
    </thead>
    <tbody>
      {_machine_rows(machines)}
    </tbody>
  </table>

  <h3 style="color:#1565c0">Device Summary</h3>
  <table style="border-collapse:collapse;width:60%;margin-bottom:24px">
    <thead>
      <tr style="background:#1565c0;color:white">
        <th style="padding:10px 12px;text-align:left">Device Type</th>
        <th style="padding:10px 12px;text-align:left">Status</th>
      </tr>
    </thead>
    <tbody>
      {_device_rows(device_counts)}
    </tbody>
  </table>

  <h3 style="color:#1565c0">Android Perf Machines Status</h3>
  <table style="border-collapse:collapse;width:60%">
    <thead>
      <tr style="background:#1565c0;color:white">
        <th style="padding:10px 12px;text-align:left">Check</th>
        <th style="padding:10px 12px;text-align:center">Status</th>
      </tr>
    </thead>
    <tbody>
      {_android_status_rows(android_status)}
    </tbody>
  </table>

  {_jenkins_section(jenkins_nodes or [], jenkins_jobs or [])}

  {_kraft_section(kraft_status or {})}

  {_books_accounts_section(books_accounts or {})}

  {_xcode_section(xcode_status or {})}

  <p style="margin-top:32px;color:#999;font-size:12px">
    This report was automatically generated by the Lab Maintenance Tool.
  </p>
</body>
</html>"""
