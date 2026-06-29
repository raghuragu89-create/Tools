"""
TestRail Analyzer — Polling Agent
Runs on a VPN-connected machine (laptop/corp server).
Polls TestRail every 5 minutes for new/updated TCs, analyzes them, pushes results to S3 dashboard via API Gateway.

Usage:
  python polling_agent.py                  # Run continuously (polls every 5 min)
  python polling_agent.py --once           # Run once and exit
  python polling_agent.py --interval 10    # Poll every 10 minutes

Setup:
  1. Place on any machine with VPN access to TestRail
  2. Configure SETTINGS below (or use environment variables)
  3. Run: python polling_agent.py
  4. Optionally: set up as Windows Task Scheduler / systemd service
"""

import json, os, time, re, sys, base64, logging
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path

# =============================================================================
# SETTINGS (edit these or set as environment variables)
# =============================================================================
TESTRAIL_URL = os.environ.get("TESTRAIL_URL", "https://your-instance.testrail.io")
TESTRAIL_EMAIL = os.environ.get("TESTRAIL_EMAIL", "your-email@example.com")
TESTRAIL_KEY = os.environ.get("TESTRAIL_KEY", "")  # Your TestRail API key
PUBLISH_ENDPOINT = os.environ.get("PUBLISH_ENDPOINT", "https://YOUR-API.execute-api.REGION.amazonaws.com/prod/webhook")
AI_ANALYZE_ENDPOINT = os.environ.get("AI_ANALYZE_ENDPOINT", "https://YOUR-API.execute-api.REGION.amazonaws.com/prod/analyze")
PUBLISH_API_KEY = os.environ.get("PUBLISH_API_KEY", "")  # API Gateway key (optional)
POLL_INTERVAL_MIN = int(os.environ.get("POLL_INTERVAL_MIN", "60"))
PROJECT_IDS = os.environ.get("PROJECT_IDS", "51")  # Comma-separated project IDs to monitor (empty = all)

# State file to track last poll time
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".polling_state.json")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("polling_agent")

# --- Automation Keywords (same as desktop tool) ---
AUTOMATION_KEYWORDS = {
    "click", "tap", "navigate", "open", "login", "logout", "select", "enter", "type",
    "verify", "assert", "check", "validate", "confirm", "compare", "load", "download",
    "upload", "submit", "search", "filter", "scroll", "swipe", "drag", "drop", "refresh",
    "api", "request", "response", "endpoint", "url", "http", "json", "xml", "rest",
    "database", "query", "sql", "table", "install", "update", "build", "deploy", "sideload",
}
_KW_RE = re.compile(r'\b(' + '|'.join(re.escape(kw) for kw in AUTOMATION_KEYWORDS) + r')\b')


# =============================================================================
# TESTRAIL CLIENT
# =============================================================================
class TestRailClient:
    def __init__(self):
        self.base = TESTRAIL_URL.rstrip("/")
        self.auth = base64.b64encode(f"{TESTRAIL_EMAIL}:{TESTRAIL_KEY}".encode()).decode()
        self._prefix = "/index.php?/api/v2/"
        try:
            self._get("get_user_by_email&email=" + TESTRAIL_EMAIL)
        except:
            self._prefix = "/api/v2/"
        log.info(f"Connected to TestRail: {self.base} (prefix: {self._prefix})")

    def _get(self, endpoint):
        url = self.base + self._prefix + endpoint
        req = Request(url)
        req.add_header("Authorization", f"Basic {self.auth}")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        return data

    def get_projects(self):
        result = self._get("get_projects")
        if isinstance(result, dict):
            return result.get("projects", [])
        return result if isinstance(result, list) else []

    def get_cases(self, project_id, suite_id=None, updated_after=None):
        """Fetch cases with optional updated_after filter (Unix timestamp)."""
        ep = f"get_cases/{project_id}"
        params = []
        if suite_id:
            params.append(f"suite_id={suite_id}")
        if updated_after:
            params.append(f"updated_after={int(updated_after)}")
        if params:
            ep += "&" + "&".join(params)
        # Handle pagination
        all_cases = []
        offset = 0
        while True:
            paged_ep = ep + f"&limit=250&offset={offset}"
            result = self._get(paged_ep)
            if isinstance(result, dict):
                cases = result.get("cases", [])
                all_cases.extend(cases)
                if result.get("_links", {}).get("next"):
                    offset += 250
                else:
                    break
            else:
                all_cases.extend(result if isinstance(result, list) else [])
                break
        return all_cases

    def get_suites(self, project_id):
        result = self._get(f"get_suites/{project_id}")
        return result if isinstance(result, list) else []

    def get_section(self, section_id):
        try:
            return self._get(f"get_section/{section_id}").get("name", "General")
        except:
            return "General"

    def get_project(self, project_id):
        return self._get(f"get_project/{project_id}")

    def get_user(self, user_id):
        try:
            return self._get(f"get_user/{user_id}")
        except:
            return {}


# =============================================================================
# HEURISTIC SCORING (same as desktop tool)
# =============================================================================
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

    if ns > 0: score += 10; reasons.append(f"Has {ns} step(s) (+10)")
    if ns > 2: score += 5; reasons.append("Detailed steps (+5)")

    kw_unique = set(_KW_RE.findall(all_text))
    if kw_unique:
        pts = min(len(kw_unique) * 2, 16)
        score += pts
        reasons.append(f"{len(kw_unique)} keywords (+{pts})")

    if expected.strip(): score += 10; reasons.append("Has expected (+10)")
    if len(expected) > 50: score += 5; reasons.append("Detailed expected (+5)")
    elif expected.strip(): score += 2; reasons.append("Brief expected (+2)")

    def has_word(words):
        return any(re.search(r'\b' + w + r'\b', all_text) for w in words)

    is_ui = has_word(["click", "tap", "button", "page", "screen", "ui", "browser", "navigate"])
    is_api = has_word(["api", "endpoint", "request", "response", "rest", "http", "json"])
    is_perf = has_word(["performance", "load", "stress", "concurrent", "latency"])
    is_device = has_word(["device", "adb", "sideload", "firmware"])

    if is_perf: test_type, tools = "Performance", ["Locust/JMeter", "CloudWatch Synthetics"]
    elif is_api: test_type, tools = "API", ["pytest", "REST Assured", "Hydra/ToD"]
    elif is_ui: test_type, tools = "UI", ["Selenium", "Cypress", "AWS Device Farm"]
    elif is_device: test_type, tools = "E2E", ["Appium", "ADB", "AWS Device Farm"]
    else: test_type, tools = "Unknown", ["Selenium", "Cypress"]

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


# =============================================================================
# PUBLISH TO LAMBDA → S3 DASHBOARD
# =============================================================================


# =============================================================================
# EMAIL NOTIFICATION (via Amazon corp SMTP — no auth needed on VPN)
# =============================================================================
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

SMTP_HOST = "smtp.your-provider.com"
SMTP_PORT = 25
FROM_EMAIL = "analyzer@example.com"


def send_notification_email(to_email, to_name, project_name, results, dashboard_url, excel_path):
    """Send analysis results email to TC creator."""
    if not to_email:
        return False
    try:
        auto = sum(1 for r in results if r.get("label") == "Automatable")
        partial = sum(1 for r in results if r.get("label") == "Partially Automatable")
        not_auto = len(results) - auto - partial

        msg = MIMEMultipart()
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg["Subject"] = f"[TestRail Analyzer] {len(results)} TCs analyzed - {project_name}"

        body = f"""Hi {to_name or 'there'},

Your recently created/updated test cases have been automatically analyzed for automation feasibility.

Summary:
  Total TCs analyzed: {len(results)}
  Automatable: {auto}
  Partially Automatable: {partial}
  Not Automatable: {not_auto}

Dashboard (live, auto-updates):
  {dashboard_url}

Top results:
"""
        for r in sorted(results, key=lambda x: -x.get("score", 0))[:10]:
            body += f"  TC-{r['testCaseId']}: {r['title'][:50]} -> {r['label']} ({r['score']}/46)\n"

        if len(results) > 10:
            body += f"  ... and {len(results) - 10} more (see Excel attachment)\n"

        body += """

Excel report attached with full details.

--
TestRail Analyzer Pipeline (automated)
"""
        msg.attach(MIMEText(body, "plain"))

        # Attach Excel if exists
        if excel_path and os.path.exists(excel_path):
            with open(excel_path, "rb") as f:
                part = MIMEBase("application", "vnd.ms-excel")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(excel_path)}"')
            msg.attach(part)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        log.info(f"  Email sent to {to_email}")
        return True
    except Exception as e:
        log.warning(f"  Email failed to {to_email}: {e}")
        return False


# =============================================================================
# EXCEL REPORT GENERATION
# =============================================================================
def generate_excel_report(project_name, results, output_dir):
    """Generate Excel report matching desktop tool output format."""
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"Automation_{project_name}_{ts}.xls"
        fpath = os.path.join(output_dir, fname)
        os.makedirs(output_dir, exist_ok=True)

        auto = sum(1 for r in results if r.get("label") == "Automatable")
        partial = sum(1 for r in results if r.get("label") == "Partially Automatable")
        not_auto = len(results) - auto - partial
        total_effort = sum(r.get("effort", 0) for r in results)

        xml = '<?xml version="1.0"?>\n'
        xml += '<?mso-application progid="Excel.Sheet"?>\n'
        xml += '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"'
        xml += ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">\n'

        # Summary sheet
        xml += '<Worksheet ss:Name="Summary"><Table>\n'
        xml += '<Row><Cell><Data ss:Type="String">TestRail Analyzer - Pipeline Report</Data></Cell></Row>\n'
        xml += f'<Row><Cell><Data ss:Type="String">Project</Data></Cell><Cell><Data ss:Type="String">{project_name}</Data></Cell></Row>\n'
        xml += f'<Row><Cell><Data ss:Type="String">Generated</Data></Cell><Cell><Data ss:Type="String">{ts}</Data></Cell></Row>\n'
        xml += f'<Row><Cell><Data ss:Type="String">Total TCs</Data></Cell><Cell><Data ss:Type="Number">{len(results)}</Data></Cell></Row>\n'
        xml += f'<Row><Cell><Data ss:Type="String">Automatable</Data></Cell><Cell><Data ss:Type="Number">{auto}</Data></Cell></Row>\n'
        xml += f'<Row><Cell><Data ss:Type="String">Partially Automatable</Data></Cell><Cell><Data ss:Type="Number">{partial}</Data></Cell></Row>\n'
        xml += f'<Row><Cell><Data ss:Type="String">Not Automatable</Data></Cell><Cell><Data ss:Type="Number">{not_auto}</Data></Cell></Row>\n'
        xml += f'<Row><Cell><Data ss:Type="String">Total Effort (days)</Data></Cell><Cell><Data ss:Type="Number">{total_effort}</Data></Cell></Row>\n'
        xml += '</Table></Worksheet>\n'

        # Results sheet
        xml += '<Worksheet ss:Name="Results"><Table>\n'
        headers = ["TC ID", "Title", "Section", "Verdict", "Score", "Confidence", "Type", "Tools", "Complexity", "Timeline", "Reasoning"]
        xml += '<Row>' + ''.join(f'<Cell><Data ss:Type="String">{h}</Data></Cell>' for h in headers) + '</Row>\n'
        for r in sorted(results, key=lambda x: -x.get("score", 0)):
            tools_str = ", ".join(r.get("tools", [])) if isinstance(r.get("tools"), list) else str(r.get("tools", ""))
            xml += '<Row>'
            xml += f'<Cell><Data ss:Type="Number">{r.get("testCaseId", "")}</Data></Cell>'
            xml += f'<Cell><Data ss:Type="String">{r.get("title", "")}</Data></Cell>'
            xml += f'<Cell><Data ss:Type="String">{r.get("section", "")}</Data></Cell>'
            xml += f'<Cell><Data ss:Type="String">{r.get("label", "")}</Data></Cell>'
            xml += f'<Cell><Data ss:Type="Number">{r.get("score", 0)}</Data></Cell>'
            xml += f'<Cell><Data ss:Type="String">{r.get("confidence", "")}</Data></Cell>'
            xml += f'<Cell><Data ss:Type="String">{r.get("testType", "")}</Data></Cell>'
            xml += f'<Cell><Data ss:Type="String">{tools_str}</Data></Cell>'
            xml += f'<Cell><Data ss:Type="String">{r.get("complexity", "")}</Data></Cell>'
            xml += f'<Cell><Data ss:Type="String">{r.get("timeline", "")}</Data></Cell>'
            xml += f'<Cell><Data ss:Type="String">{r.get("reasoning", "")}</Data></Cell>'
            xml += '</Row>\n'
        xml += '</Table></Worksheet>\n'
        xml += '</Workbook>'

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(xml)

        log.info(f"  Excel report: {fpath}")
        return fpath
    except Exception as e:
        log.warning(f"  Excel generation failed: {e}")
        return None
def ai_deep_analysis(cases_batch):
    """Call /analyze endpoint for AI-enriched results. Returns list of AI results or empty."""
    try:
        tcs_payload = []
        for tc in cases_batch:
            tcs_payload.append({
                "id": tc.get("id", 0),
                "title": tc.get("title", ""),
                "steps": tc.get("custom_steps", ""),
                "expected": tc.get("custom_expected", ""),
                "preconditions": tc.get("custom_preconds", ""),
            })
        payload = json.dumps({"action": "analyze", "testCases": tcs_payload}).encode()
        req = Request(AI_ANALYZE_ENDPOINT, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        # Handle Lambda proxy response
        if isinstance(data, dict) and "body" in data:
            body = json.loads(data["body"]) if isinstance(data["body"], str) else data["body"]
            return body.get("results", [])
        return data.get("results", [])
    except Exception as e:
        log.warning(f"  AI analysis failed: {e}")
        return []

def publish_results(project_name, results, notify_email=""):
    """Push analyzed results to Lambda which stores in S3 + updates dashboard."""
    payload = json.dumps({
        "action": "publish",
        "project_name": project_name,
        "results": results,
        "notify_email": notify_email,
    }).encode()

    req = Request(PUBLISH_ENDPOINT, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    if PUBLISH_API_KEY:
        req.add_header("x-api-key", PUBLISH_API_KEY)

    try:
        with urlopen(req, timeout=30) as resp:
            response = json.loads(resp.read())
            return response
    except HTTPError as e:
        body = e.read().decode() if hasattr(e, 'read') else str(e)
        log.error(f"Publish failed: {e.code} — {body}")
        return None
    except Exception as e:
        log.error(f"Publish error: {e}")
        return None


# =============================================================================
# STATE MANAGEMENT
# =============================================================================
def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except:
        pass
    return {"last_poll": 0, "analyzed_ids": {}}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save state: {e}")

# POLLING LOGIC
# =============================================================================
def poll_once(client, state):
    last_poll = state.get("last_poll", 0)
    now = int(time.time())
    if last_poll == 0:
        last_poll = now - 86400
        log.info("First run - checking TCs from last 24 hours")
    if PROJECT_IDS:
        project_ids = [int(x.strip()) for x in PROJECT_IDS.split(",") if x.strip()]
    else:
        projects = client.get_projects()
        project_ids = [p["id"] for p in projects if p.get("is_completed") != True]
        log.info(f"Monitoring {len(project_ids)} active projects")
    total_new = 0
    total_analyzed = 0
    for pid in project_ids:
        try:
            project = client.get_project(pid)
            project_name = project.get("name", f"Project_{pid}").replace(" ", "_")
            cases = []
            try:
                cases = client.get_cases(pid, updated_after=last_poll)
            except:
                try:
                    suites = client.get_suites(pid)
                    for suite in suites:
                        try:
                            sc = client.get_cases(pid, suite_id=suite.get("id"), updated_after=last_poll)
                            cases.extend(sc)
                        except:
                            pass
                except:
                    pass
            if not cases:
                continue
            log.info(f"[{project_name}] Found {len(cases)} new/updated TCs since last poll")
            total_new += len(cases)
            ai_results_map = {}
            batch_size = 3
            batches_list = [cases[i:i+batch_size] for i in range(0, len(cases), batch_size)]
            for bi, batch in enumerate(batches_list):
                log.info(f"  [AI] Batch {bi+1}/{len(batches_list)} ({len(batch)} TCs)...")
                ai_batch = ai_deep_analysis(batch)
                for ai_r in ai_batch:
                    ai_results_map[ai_r.get('testCaseId', 0)] = ai_r
            results = []
            for tc in cases:
                cid = tc.get("id", 0)
                section_id = tc.get("section_id")
                section = client.get_section(section_id) if section_id else "General"
                h = heuristic_score(tc)
                ai = ai_results_map.get(cid, {})
                results.append({
                    "testCaseId": cid, "title": tc.get("title", ""), "section": section,
                    "score": h["score"],
                    "label": ai.get("automatability", h["label"]),
                    "confidence": ai.get("confidence", h["confidence"]),
                    "reasoning": ai.get("reasoning", h["reasoning"]),
                    "testType": ai.get("testType", h["testType"]),
                    "tools": ai.get("recommendedTools", ", ".join(h["tools"])) if ai else h["tools"],
                    "complexity": ai.get("complexity", h["complexity"]),
                    "timeline": ai.get("expectedTimeline", h["timeline"]),
                    "effort": ai.get("estimatedEffortDays", h["effort"]),
                    "approach": ai.get("automationApproach", ""),
                    "prerequisites": ai.get("prerequisites", ""),
                    "event": "poll_detected",
                    "analyzed_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                })
            if results:
                log.info(f"[{project_name}] Publishing {len(results)} results...")
                primary_creator = cases[0].get("created_by", 0) if cases else 0
                creator_email = ""
                if primary_creator:
                    u = client.get_user(primary_creator)
                    creator_email = u.get("email", "")
                response = publish_results(project_name, results, notify_email=creator_email)
                if response:
                    log.info(f"[{project_name}] Published!")
                    total_analyzed += len(results)
                    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
                    generate_excel_report(project_name, results, report_dir)
                else:
                    log.warning(f"[{project_name}] Publish failed")
        except Exception as e:
            log.error(f"Error processing project {pid}: {e}")
            continue
    state["last_poll"] = now
    save_state(state)
    if total_new == 0:
        log.info("No new/updated TCs found.")
    else:
        log.info(f"Poll complete: {total_new} detected, {total_analyzed} analyzed + published.")
    return total_analyzed



# =============================================================================
def main():
    # Parse args
    run_once = "--once" in sys.argv
    interval = POLL_INTERVAL_MIN
    for i, arg in enumerate(sys.argv):
        if arg == "--interval" and i + 1 < len(sys.argv):
            interval = int(sys.argv[i + 1])

    # Validate config
    if not TESTRAIL_KEY:
        log.error("TESTRAIL_KEY not set! Set via environment variable or edit SETTINGS in this file.")
        sys.exit(1)

    log.info("=" * 60)
    log.info("TestRail Analyzer — Polling Agent")
    log.info(f"  TestRail: {TESTRAIL_URL}")
    log.info(f"  Endpoint: {PUBLISH_ENDPOINT}")
    log.info(f"  Interval: {interval} min")
    log.info(f"  Projects: {PROJECT_IDS or 'ALL'}")
    log.info(f"  Mode: {'once' if run_once else 'continuous'}")
    log.info("=" * 60)

    # Connect to TestRail
    try:
        client = TestRailClient()
    except Exception as e:
        log.error(f"Cannot connect to TestRail: {e}")
        sys.exit(1)

    state = load_state()

    if run_once:
        poll_once(client, state)
        return

    # Continuous polling
    log.info(f"Starting continuous polling (every {interval} min). Press Ctrl+C to stop.")
    while True:
        try:
            poll_once(client, state)
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as e:
            log.error(f"Poll error: {e}")

        log.info(f"Next poll in {interval} minutes...")
        try:
            time.sleep(interval * 60)
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break


if __name__ == "__main__":
    main()
