import json, boto3, os, re, time, hashlib, base64
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# --- Existing: AI Analysis via Bedrock ---
bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("BEDROCK_REGION", "us-east-1"))
s3 = boto3.client("s3")
MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")

# --- Config ---
TESTRAIL_URL = os.environ.get("TESTRAIL_URL", "")
TESTRAIL_EMAIL = os.environ.get("TESTRAIL_EMAIL", "")
TESTRAIL_KEY = os.environ.get("TESTRAIL_KEY", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "your-s3-bucket-name")

PROMPT = """You are a senior test automation architect. Analyze EACH test case and determine automation feasibility.
For EACH test case return a JSON object with:
- testCaseId (number)
- automatability: "Automatable" | "Partially Automatable" | "Not Automatable"
- confidence: "High" | "Medium" | "Low"
- reasoning: 3-5 sentences referencing SPECIFIC steps
- automationApproach: Concrete step-by-step with specific tools
- recommendedTools: CSV of tools
- expectedTimeline: e.g. "2-3 days"
- complexity: "Low" | "Medium" | "High"
- prerequisites: Specific env/data/access needed
- testType: Unit|Integration|E2E|API|UI|Performance|Security|Accessibility|Manual-Only
- estimatedEffortDays: number
Return ONLY a valid JSON array."""

# --- Automation Keywords ---
AUTOMATION_KEYWORDS = {
    "click", "tap", "navigate", "open", "login", "logout", "select", "enter", "type",
    "verify", "assert", "check", "validate", "confirm", "compare", "load", "download",
    "upload", "submit", "search", "filter", "scroll", "swipe", "drag", "drop", "refresh",
    "api", "request", "response", "endpoint", "url", "http", "json", "xml", "rest",
    "database", "query", "sql", "table", "install", "update", "build", "deploy", "sideload",
}
_KW_RE = re.compile(r'\b(' + '|'.join(re.escape(kw) for kw in AUTOMATION_KEYWORDS) + r')\b')


# =============================================================================
# MAIN HANDLER
# =============================================================================
def handler(event, context):
    path = event.get("rawPath", "") or event.get("resource", "") or event.get("path", "") or ""

    try:
        body = json.loads(event.get("body", "{}")) if isinstance(event.get("body"), str) else (event.get("body") or event)
    except:
        body = event

    # Route to webhook if path matches OR body has webhook fields
    # Route to webhook/publish
    if "/webhook" in path or "case_id" in body or str(body.get("event", "")).startswith("case_"):
        return handle_webhook_parsed(body)
    if body.get("action") == "publish":
        return handle_publish(body)
        return handle_webhook_parsed(body)

    # Default: existing analyze logic
    action = body.get("action", "analyze")
    if action == "health":
        return resp(200, {"status": "ok", "model": MODEL_ID})
    if action != "analyze":
        return resp(400, {"error": f"Unknown action: {action}"})

    tcs = body.get("testCases", [])
    if not tcs:
        return resp(400, {"error": "No testCases"})

    txt = ""
    for tc in tcs:
        txt += f"\n---\nID: {tc.get('id','?')}\nTitle: {tc.get('title','')}\n"
        for f in ["summary", "steps", "expected", "preconditions"]:
            if tc.get(f):
                txt += f"{f}: {tc[f][:800]}\n"
    try:
        r = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": PROMPT + "\n\n" + txt}]
            })
        )
        t = json.loads(r["body"].read())["content"][0]["text"].strip()
        if t.startswith("```"):
            t = re.sub(r"^```\w*\n?", "", t)
            t = re.sub(r"\n?```$", "", t)
        return resp(200, {"results": json.loads(t), "count": len(json.loads(t)), "model": MODEL_ID})
    except Exception as e:
        return resp(500, {"error": str(e)})


# =============================================================================
# WEBHOOK HANDLER
# =============================================================================
def handle_webhook_parsed(body):
    try:
        if body.get("action") == "full_scan":
            return handle_full_scan(body)

        event_type = body.get("event", "")
        case_id = body.get("case_id") or body.get("id")

        if not case_id:
            return resp(400, {"error": "No case_id in webhook payload"})

        if event_type and event_type not in ("case_created", "case_updated", "case_changed"):
            return resp(200, {"message": f"Ignoring event: {event_type}"})

        client = TestRailClient(TESTRAIL_URL, TESTRAIL_EMAIL, TESTRAIL_KEY)
        tc = client.get_case(case_id)
        section_id = tc.get("section_id")
        section = client.get_section(section_id) if section_id else "General"

        try:
            proj = client.get_project(tc.get("project_id", 0))
            project_name = proj.get("name", "Unknown").replace(" ", "_")
        except:
            project_name = f"Project_{tc.get('project_id', 0)}"

        h = heuristic_score(tc)

        result = {
            "testCaseId": case_id,
            "title": tc.get("title", ""),
            "section": section,
            "score": h["score"],
            "label": h["label"],
            "confidence": h["confidence"],
            "reasoning": h["reasoning"],
            "testType": h["testType"],
            "tools": h["tools"],
            "complexity": h["complexity"],
            "timeline": h["timeline"],
            "effort": h["effort"],
            "event": event_type or "manual",
            "analyzed_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
        }

        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"results/{project_name}/{case_id}.json",
            Body=json.dumps(result, indent=2),
            ContentType="application/json"
        )

        dashboard = load_dashboard_data(project_name)
        dashboard["project"] = project_name
        dashboard["results"][str(case_id)] = result
        save_dashboard(project_name, dashboard)

        dashboard_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": f"dashboard/{project_name}/index.html"},
            ExpiresIn=604800
        )

        return resp(200, {
            "status": "analyzed",
            "case_id": case_id,
            "title": tc.get("title", ""),
            "label": result["label"],
            "score": result["score"],
            "dashboard": dashboard_url,
        })

    except Exception as e:
        return resp(500, {"error": str(e)})


def handle_full_scan(body):
    project_id = body.get("project_id")
    if not project_id:
        return resp(400, {"error": "project_id required"})
    return resp(200, {"status": "full_scan_queued", "message": "Full scan initiated."})



ses = boto3.client("ses", region_name="us-east-1")
FROM_EMAIL = "your-email@example.com"

def send_ses_email(to_email, project_name, results, dashboard_url):
    """Send analysis notification via AWS SES."""
    if not to_email or not results:
        return
    try:
        auto = sum(1 for r in results if r.get("label") == "Automatable")
        partial = sum(1 for r in results if r.get("label") == "Partially Automatable")
        not_auto = len(results) - auto - partial
        top = "\n".join(f"  TC-{r['testCaseId']}: {r.get('title','')[:50]} -> {r['label']} ({r['score']}/46)" for r in sorted(results, key=lambda x: -x.get("score",0))[:10])
        body_text = (
            f"Your test cases have been automatically analyzed for automation feasibility.\n\n"
            f"Summary:\n  Total: {len(results)}\n  Automatable: {auto}\n  Partial: {partial}\n  Not Automatable: {not_auto}\n\n"
            f"Dashboard (live):\n  {dashboard_url}\n\nTop results:\n{top}\n\n--\nTestRail Analyzer Pipeline"
        )
        ses.send_email(
            Source=FROM_EMAIL,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": f"[TestRail Analyzer] {len(results)} TCs analyzed - {project_name}"},
                "Body": {"Text": {"Data": body_text}}
            }
        )
    except Exception as e:
        pass  # Silent fail for email
def handle_publish(body):
    """Receive pre-analyzed results from polling agent and store to S3 dashboard."""
    try:
        project_name = body.get("project_name", "Unknown")
        results = body.get("results", [])
        if not results and not body.get("project_name"):
            return resp(400, {"error": "No results in publish payload"})
        dashboard = load_dashboard_data(project_name)
        dashboard["project"] = project_name
        for r in results:
            tc_id = str(r.get("testCaseId", ""))
            if tc_id:
                dashboard["results"][tc_id] = r
        save_dashboard(project_name, dashboard)
        dashboard_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": f"dashboard/{project_name}/index.html"},
            ExpiresIn=604800
        )
        # Send email notification via SES
        notify_email = body.get("notify_email", "")
        if notify_email:
            send_ses_email(notify_email, project_name, results, dashboard_url)
        return resp(200, {
            "status": "published",
            "project": project_name,
            "count": len(results),
            "total": len(dashboard["results"]),
            "dashboard": dashboard_url,
        })
    except Exception as e:
        return resp(500, {"error": str(e)})


# =============================================================================
# TESTRAIL API CLIENT
# =============================================================================
class TestRailClient:
    def __init__(self, url, email, key):
        self.base = url.rstrip("/")
        self.auth = base64.b64encode(f"{email}:{key}".encode()).decode()
        self._prefix = "/index.php?/api/v2/"
        try:
            self._get("get_user_by_email&email=" + email)
        except:
            self._prefix = "/api/v2/"

    def _get(self, endpoint):
        url = self.base + self._prefix + endpoint
        req = Request(url)
        req.add_header("Authorization", f"Basic {self.auth}")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    def get_case(self, case_id):
        return self._get(f"get_case/{case_id}")

    def get_section(self, section_id):
        try:
            return self._get(f"get_section/{section_id}").get("name", "General")
        except:
            return "General"

    def get_project(self, project_id):
        return self._get(f"get_project/{project_id}")


# =============================================================================
# HEURISTIC SCORING
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
# S3 DASHBOARD
# =============================================================================
def load_dashboard_data(project_name):
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=f"dashboard/{project_name}/data.json")
        return json.loads(obj["Body"].read())
    except:
        return {"project": project_name, "results": {}, "last_updated": "", "stats": {}}


def save_dashboard(project_name, data):
    data["last_updated"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    results = data.get("results", {})
    total = len(results)
    auto = sum(1 for r in results.values() if r.get("label") == "Automatable")
    partial = sum(1 for r in results.values() if r.get("label") == "Partially Automatable")
    data["stats"] = {
        "total": total, "automatable": auto, "partial": partial,
        "not_automatable": total - auto - partial,
        "automation_rate": round(auto / max(total, 1) * 100, 1),
    }
    s3.put_object(Bucket=S3_BUCKET, Key=f"dashboard/{project_name}/data.json",
                  Body=json.dumps(data, indent=2), ContentType="application/json")
    html = generate_dashboard_html(data)
    s3.put_object(Bucket=S3_BUCKET, Key=f"dashboard/{project_name}/index.html",
                  Body=html, ContentType="text/html")


def generate_dashboard_html(data):
    stats = data.get("stats", {})
    results = data.get("results", {})
    project = data.get("project", "Unknown")
    updated = data.get("last_updated", "")
    rows = ""
    for tc_id, r in sorted(results.items(), key=lambda x: -x[1].get("score", 0)):
        label = r.get("label", "Unknown")
        cls = "green" if label == "Automatable" else ("yellow" if "Partial" in label else "red")
        rows += f'<tr><td>{tc_id}</td><td>{r.get("title","")}</td><td>{r.get("section","")}</td>'
        rows += f'<td><span class="b {cls}">{label}</span></td><td>{r.get("score",0)}/46</td>'
        rows += f'<td>{r.get("testType","")}</td><td>{", ".join(r.get("tools",[]))}</td>'
        rows += f'<td>{r.get("complexity","")}</td><td>{r.get("analyzed_at","")}</td></tr>'
    return f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<title>TestRail Analyzer - {project}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',sans-serif;background:#0f0f14;color:#fafafa;padding:24px}}
h1{{font-size:1.5rem;margin-bottom:4px}}.sub{{color:#71717a;margin-bottom:20px}}
.cards{{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}}
.card{{background:#1a1a24;border-radius:8px;padding:14px 20px;min-width:120px}}
.card .v{{font-size:1.8rem;font-weight:700}}.card .l{{color:#a1a1aa;font-size:.75rem;text-transform:uppercase}}
.card.green .v{{color:#22c55e}}.card.yellow .v{{color:#eab308}}.card.red .v{{color:#ef4444}}.card.blue .v{{color:#3b82f6}}
table{{width:100%;border-collapse:collapse;background:#1a1a24;border-radius:8px;overflow:hidden}}
th{{background:#252530;padding:8px 10px;text-align:left;font-size:.7rem;text-transform:uppercase;color:#a1a1aa}}
td{{padding:7px 10px;border-top:1px solid #252530;font-size:.82rem}}tr:hover{{background:#252530}}
.b{{padding:2px 6px;border-radius:4px;font-size:.7rem;font-weight:600}}
.b.green{{background:#052e16;color:#22c55e}}.b.yellow{{background:#422006;color:#eab308}}.b.red{{background:#450a0a;color:#ef4444}}
input{{background:#252530;border:1px solid #333;color:#fafafa;padding:7px 12px;border-radius:6px;width:280px;margin-bottom:12px}}
</style></head><body>
<h1>TestRail Analyzer - {project}</h1>
<p class="sub">Updated: {updated} | Pipeline: Real-time webhook</p>
<div class="cards">
<div class="card blue"><div class="v">{stats.get("total",0)}</div><div class="l">Total</div></div>
<div class="card green"><div class="v">{stats.get("automatable",0)}</div><div class="l">Automatable</div></div>
<div class="card yellow"><div class="v">{stats.get("partial",0)}</div><div class="l">Partial</div></div>
<div class="card red"><div class="v">{stats.get("not_automatable",0)}</div><div class="l">Not Auto</div></div>
<div class="card green"><div class="v">{stats.get("automation_rate",0)}%</div><div class="l">Rate</div></div>
</div>
<input type="text" placeholder="Search..." oninput="f(this.value)">
<table><thead><tr><th>ID</th><th>Title</th><th>Section</th><th>Verdict</th><th>Score</th><th>Type</th><th>Tools</th><th>Complexity</th><th>Analyzed</th></tr></thead>
<tbody>{rows}</tbody></table>
<script>function f(q){{document.querySelectorAll('tbody tr').forEach(r=>r.style.display=!q||r.textContent.toLowerCase().includes(q.toLowerCase())?'':'none')}}</script>
</body></html>'''


# =============================================================================
# RESPONSE HELPER
# =============================================================================
def resp(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,x-api-key"
        },
        "body": json.dumps(body)
    }
