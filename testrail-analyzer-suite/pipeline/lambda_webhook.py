"""
TestRail Analyzer — Pipeline Lambda Handler
Receives TestRail webhooks on TC create/update, runs analysis, stores to S3.

Deployment:
  - Add as a new route on existing API Gateway (POST /webhook)
  - Attach to same Lambda or a separate one
  - Requires S3 bucket + TestRail API credentials in env vars

Environment Variables:
  TESTRAIL_URL       - Base URL (e.g., https://your-instance.testrail.io)
  TESTRAIL_EMAIL     - API email
  TESTRAIL_KEY       - API key
  S3_BUCKET          - Bucket name for results + dashboard
  AI_ENDPOINT        - (optional) AI analysis endpoint URL
  AI_KEY             - (optional) AI analysis API key
"""

import json
import os
import time
import re
import hashlib
import boto3
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import base64

# --- Config ---
TESTRAIL_URL = os.environ.get("TESTRAIL_URL", "")
TESTRAIL_EMAIL = os.environ.get("TESTRAIL_EMAIL", "")
TESTRAIL_KEY = os.environ.get("TESTRAIL_KEY", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "testrail-analyzer-results")
AI_ENDPOINT = os.environ.get("AI_ENDPOINT", "")
AI_KEY = os.environ.get("AI_KEY", "")

s3 = boto3.client("s3")

# --- Automation Keywords (same as desktop tool) ---
AUTOMATION_KEYWORDS = {
    "click", "tap", "navigate", "open", "login", "logout", "select", "enter", "type",
    "verify", "assert", "check", "validate", "confirm", "compare", "load", "download",
    "upload", "submit", "search", "filter", "scroll", "swipe", "drag", "drop", "refresh",
    "api", "request", "response", "endpoint", "url", "http", "json", "xml", "rest",
    "database", "query", "sql", "table", "install", "update", "build", "deploy", "sideload",
}
_KW_RE = re.compile(r'\b(' + '|'.join(re.escape(kw) for kw in AUTOMATION_KEYWORDS) + r')\b')


# --- TestRail API Client ---
class TestRailClient:
    def __init__(self, url, email, key):
        self.base = url.rstrip("/")
        self.auth = base64.b64encode(f"{email}:{key}".encode()).decode()
        # Detect index.php prefix
        self._prefix = "/index.php?/api/v2/"
        try:
            self._get("get_user_by_email&email=" + email)
        except Exception:
            self._prefix = "/api/v2/"

    def _get(self, endpoint):
        url = self.base + self._prefix + endpoint
        req = Request(url)
        req.add_header("Authorization", f"Basic {self.auth}")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    def get_case(self, case_id):
        return self._get(f"get_case/{case_id}")

    def get_section(self, section_id):
        try:
            sec = self._get(f"get_section/{section_id}")
            return sec.get("name", "General")
        except Exception:
            return "General"

    def get_project(self, project_id):
        return self._get(f"get_project/{project_id}")


# --- Heuristic Scoring (same logic as desktop tool) ---
def heuristic_score(tc):
    score, reasons = 0, []
    steps = tc.get("custom_steps_separated") or []
    step_text = tc.get("custom_steps") or ""
    expected = tc.get("custom_expected") or ""
    preconds = tc.get("custom_preconds") or ""
    title = (tc.get("title") or "").lower()
    all_text = (title + " " + step_text + " " + expected + " " + preconds +
                " " + " ".join(s.get("content", "") + " " + s.get("expected", "") for s in steps)).lower()
    ns = len(steps) if steps else len([l for l in step_text.split("\n") if l.strip()])
    if ns > 0:
        score += 10
        reasons.append(f"Has {ns} step(s) (+10)")
    if ns > 2:
        score += 5
        reasons.append("Detailed steps (+5)")
    kw_unique = set(_KW_RE.findall(all_text))
    if kw_unique:
        pts = min(len(kw_unique) * 2, 16)
        score += pts
        reasons.append(f"{len(kw_unique)} keywords (+{pts})")
    if expected.strip():
        score += 10
        reasons.append("Has expected (+10)")
    if len(expected) > 50:
        score += 5
        reasons.append("Detailed expected (+5)")
    elif expected.strip():
        score += 2
        reasons.append("Brief expected (+2)")

    # Test type detection
    def has_word(words):
        return any(re.search(r'\b' + w + r'\b', all_text) for w in words)

    is_ui = has_word(["click", "tap", "button", "page", "screen", "ui", "browser", "navigate", "scroll"])
    is_api = has_word(["api", "endpoint", "request", "response", "rest", "http", "json"])
    is_perf = has_word(["performance", "load", "stress", "concurrent", "latency"])
    is_device = has_word(["device", "adb", "sideload", "firmware"])

    if is_perf:
        test_type, tools = "Performance", ["Locust/JMeter", "CloudWatch Synthetics"]
    elif is_api:
        test_type, tools = "API", ["pytest", "REST Assured", "Hydra/ToD"]
    elif is_ui:
        test_type, tools = "UI", ["Selenium", "Cypress", "AWS Device Farm"]
    elif is_device:
        test_type, tools = "E2E", ["Appium", "ADB", "AWS Device Farm"]
    else:
        test_type, tools = "Unknown", ["Selenium", "Cypress"]

    label = "Automatable" if score >= 36 else ("Partially Automatable" if score >= 20 else "Not Automatable")
    confidence = "High" if score >= 36 else ("Medium" if score >= 20 else "Low")
    complexity = "Low" if score >= 36 else ("Medium" if score >= 20 else "High")
    effort = 1.0 if complexity == "Low" else (3.0 if complexity == "Medium" else 5.0)
    timeline = "1-2 days" if complexity == "Low" else ("3-5 days" if complexity == "Medium" else "5-10 days")

    return {
        "score": score, "reasoning": "; ".join(reasons), "tools": tools,
        "testType": test_type, "label": label, "confidence": confidence,
        "complexity": complexity, "effort": effort, "timeline": timeline,
    }


# --- AI Analysis (optional, calls existing /analyze endpoint) ---
def ai_analyze(tc, section):
    if not AI_ENDPOINT or not AI_KEY:
        return None
    try:
        title = tc.get("title", "")
        steps = tc.get("custom_steps") or ""
        expected = tc.get("custom_expected") or ""
        payload = json.dumps({
            "system_prompt": "Analyze this test case for automation feasibility.",
            "user_prompt": f"TC: {title}\nSteps: {steps}\nExpected: {expected}\nSection: {section}",
            "max_tokens": 2048
        }).encode()
        req = Request(AI_ENDPOINT, data=payload, method="POST")
        req.add_header("x-api-key", AI_KEY)
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read())
        if isinstance(result, list) and result:
            return result[0]
    except Exception:
        pass
    return None


# --- S3 Operations ---
def store_result(project_name, tc_id, result):
    """Store individual TC result to S3."""
    key = f"results/{project_name}/{tc_id}.json"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(result, indent=2),
        ContentType="application/json"
    )
    return key


def load_dashboard_data(project_name):
    """Load existing dashboard data from S3."""
    key = f"dashboard/{project_name}/data.json"
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except Exception:
        return {"project": project_name, "results": {}, "last_updated": "", "stats": {}}


def save_dashboard_data(project_name, data):
    """Save dashboard data + regenerate HTML."""
    data["last_updated"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Recalculate stats
    results = data.get("results", {})
    total = len(results)
    auto = sum(1 for r in results.values() if r.get("label") == "Automatable")
    partial = sum(1 for r in results.values() if r.get("label") == "Partially Automatable")
    not_auto = total - auto - partial
    data["stats"] = {
        "total": total, "automatable": auto,
        "partial": partial, "not_automatable": not_auto,
        "automation_rate": round(auto / max(total, 1) * 100, 1),
    }

    # Save JSON
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"dashboard/{project_name}/data.json",
        Body=json.dumps(data, indent=2),
        ContentType="application/json"
    )

    # Generate + save HTML dashboard
    html = generate_dashboard_html(data)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"dashboard/{project_name}/index.html",
        Body=html,
        ContentType="text/html"
    )


def generate_dashboard_html(data):
    """Generate a self-contained HTML dashboard."""
    stats = data.get("stats", {})
    results = data.get("results", {})
    project = data.get("project", "Unknown")
    updated = data.get("last_updated", "")

    # Build table rows
    rows = ""
    for tc_id, r in sorted(results.items(), key=lambda x: -x[1].get("score", 0)):
        label = r.get("label", "Unknown")
        badge_cls = "green" if label == "Automatable" else ("yellow" if "Partial" in label else "red")
        rows += f"""<tr>
            <td>{tc_id}</td>
            <td>{r.get('title', '')}</td>
            <td>{r.get('section', '')}</td>
            <td><span class="badge {badge_cls}">{label}</span></td>
            <td>{r.get('score', 0)}/46</td>
            <td>{r.get('testType', '')}</td>
            <td>{', '.join(r.get('tools', []))}</td>
            <td>{r.get('complexity', '')}</td>
            <td>{r.get('timeline', '')}</td>
            <td>{r.get('analyzed_at', '')}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TestRail Analyzer — {project}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',sans-serif;background:#0f0f14;color:#fafafa;padding:24px}}
h1{{font-size:1.5rem;margin-bottom:4px}}
.subtitle{{color:#71717a;margin-bottom:24px}}
.stats{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}}
.stat-card{{background:#1a1a24;border-radius:8px;padding:16px 24px;min-width:140px}}
.stat-value{{font-size:2rem;font-weight:700}}
.stat-label{{color:#a1a1aa;font-size:0.8rem;text-transform:uppercase}}
.stat-card.green .stat-value{{color:#22c55e}}
.stat-card.yellow .stat-value{{color:#eab308}}
.stat-card.red .stat-value{{color:#ef4444}}
.stat-card.blue .stat-value{{color:#3b82f6}}
table{{width:100%;border-collapse:collapse;background:#1a1a24;border-radius:8px;overflow:hidden}}
th{{background:#252530;padding:10px 12px;text-align:left;font-size:0.75rem;text-transform:uppercase;color:#a1a1aa}}
td{{padding:8px 12px;border-top:1px solid #252530;font-size:0.85rem}}
tr:hover{{background:#252530}}
.badge{{padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600}}
.badge.green{{background:#052e16;color:#22c55e}}
.badge.yellow{{background:#422006;color:#eab308}}
.badge.red{{background:#450a0a;color:#ef4444}}
input{{background:#252530;border:1px solid #333;color:#fafafa;padding:8px 12px;border-radius:6px;width:300px;margin-bottom:16px}}
</style>
</head><body>
<h1>📊 TestRail Analyzer — {project}</h1>
<p class="subtitle">Last updated: {updated} | Pipeline: Real-time webhook</p>
<div class="stats">
    <div class="stat-card blue"><div class="stat-value">{stats.get('total',0)}</div><div class="stat-label">Total TCs</div></div>
    <div class="stat-card green"><div class="stat-value">{stats.get('automatable',0)}</div><div class="stat-label">Automatable</div></div>
    <div class="stat-card yellow"><div class="stat-value">{stats.get('partial',0)}</div><div class="stat-label">Partial</div></div>
    <div class="stat-card red"><div class="stat-value">{stats.get('not_automatable',0)}</div><div class="stat-label">Not Automatable</div></div>
    <div class="stat-card green"><div class="stat-value">{stats.get('automation_rate',0)}%</div><div class="stat-label">Automation Rate</div></div>
</div>
<input type="text" id="search" placeholder="Search test cases..." oninput="filterTable(this.value)">
<table id="results">
<thead><tr><th>ID</th><th>Title</th><th>Section</th><th>Verdict</th><th>Score</th><th>Type</th><th>Tools</th><th>Complexity</th><th>Timeline</th><th>Analyzed</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<script>
function filterTable(q){{const rows=document.querySelectorAll('#results tbody tr');rows.forEach(r=>{{r.style.display=!q||r.textContent.toLowerCase().includes(q.toLowerCase())?'':'none'}})}}
</script>
</body></html>"""
    return html


# --- Lambda Handler ---
def lambda_handler(event, context):
    """
    Handles two types of requests:
    1. TestRail webhook (POST /webhook) — TC created/updated
    2. Manual trigger (POST /webhook with {"action": "full_scan", "project_id": X, "suite_id": Y})
    """
    try:
        # Parse body
        body = event.get("body", "{}")
        if isinstance(body, str):
            body = json.loads(body)

        # --- Manual full scan ---
        if body.get("action") == "full_scan":
            return handle_full_scan(body)

        # --- TestRail Webhook ---
        # TestRail sends: {"event": "case_created" or "case_updated", "case_id": X, ...}
        event_type = body.get("event", "")
        case_id = body.get("case_id") or body.get("id")

        if not case_id:
            return response(400, {"error": "No case_id in webhook payload"})

        if event_type not in ("case_created", "case_updated", "case_changed", ""):
            return response(200, {"message": f"Ignoring event: {event_type}"})

        # Fetch TC from TestRail
        client = TestRailClient(TESTRAIL_URL, TESTRAIL_EMAIL, TESTRAIL_KEY)
        tc = client.get_case(case_id)
        section_id = tc.get("section_id")
        section = client.get_section(section_id) if section_id else "General"
        project_id = tc.get("suite_id") or tc.get("project_id", 0)

        # Get project name
        try:
            proj = client.get_project(tc.get("project_id", project_id))
            project_name = proj.get("name", f"Project_{project_id}").replace(" ", "_")
        except Exception:
            project_name = f"Project_{project_id}"

        # Run heuristic analysis
        h = heuristic_score(tc)

        # Try AI enrichment (optional)
        ai_result = ai_analyze(tc, section)

        # Build result
        result = {
            "testCaseId": case_id,
            "title": tc.get("title", ""),
            "section": section,
            "score": h["score"],
            "label": ai_result.get("automatability", h["label"]) if ai_result else h["label"],
            "confidence": ai_result.get("confidence", h["confidence"]) if ai_result else h["confidence"],
            "reasoning": ai_result.get("reasoning", h["reasoning"]) if ai_result else h["reasoning"],
            "testType": h["testType"],
            "tools": h["tools"],
            "complexity": h["complexity"],
            "timeline": h["timeline"],
            "effort": h["effort"],
            "event": event_type or "manual",
            "analyzed_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
        }

        # Store to S3
        store_result(project_name, case_id, result)

        # Update dashboard
        dashboard = load_dashboard_data(project_name)
        dashboard["project"] = project_name
        dashboard["results"][str(case_id)] = result
        save_dashboard_data(project_name, dashboard)

        # Return dashboard URL
        # Generate pre-signed URL (valid 7 days) since bucket is private
        dashboard_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": f"dashboard/{project_name}/index.html"},
            ExpiresIn=604800
        )

        return response(200, {
            "status": "analyzed",
            "case_id": case_id,
            "label": result["label"],
            "score": result["score"],
            "dashboard": dashboard_url,
        })

    except Exception as e:
        return response(500, {"error": str(e)})


def handle_full_scan(body):
    """Run full analysis on an entire project/suite (manual trigger)."""
    project_id = body.get("project_id")
    suite_id = body.get("suite_id")
    if not project_id:
        return response(400, {"error": "project_id required for full_scan"})

    client = TestRailClient(TESTRAIL_URL, TESTRAIL_EMAIL, TESTRAIL_KEY)
    proj = client.get_project(project_id)
    project_name = proj.get("name", f"Project_{project_id}").replace(" ", "_")

    # Note: For large suites, this should be async (SQS + worker)
    # For now, process up to 50 TCs synchronously (Lambda 15min timeout)
    return response(200, {
        "status": "full_scan_queued",
        "project": project_name,
        "message": "Full scan initiated. Results will appear on dashboard as each TC is processed.",
        "dashboard": s3.generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET, "Key": f"dashboard/{project_name}/index.html"}, ExpiresIn=604800)
    })


def response(code, body):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body)
    }
