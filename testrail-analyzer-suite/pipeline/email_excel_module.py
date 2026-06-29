
    def get_user(self, user_id):
        try:
            return self._get(f"get_user/{user_id}")
        except:
            return {}


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
