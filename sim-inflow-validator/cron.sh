#!/bin/bash
# SIM Inflow Validator — Cron Job (AutoSIM + AI version)
# AutoSIM handles instant validation + comment markers
# This cron handles: Move to Hold + Slack + AI analysis
LOG="/home/your-username/.sim-validator.log"
WASABI="/home/your-username/.toolbox/tools/wasabi/1.0.8769.0/wasabi"

# Skip if outside business hours (IST = UTC+5:30), 7 AM - 4 PM
HOUR_IST=$(TZ='Asia/Kolkata' date '+%H')
if [ "$HOUR_IST" -lt 7 ] || [ "$HOUR_IST" -ge 16 ]; then
  exit 0
fi

# Skip weekends
DAY=$(date '+%u')  # 1=Mon, 7=Sun
if [ "$DAY" -ge 6 ]; then
  exit 0
fi

echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] --- Cron: Starting (AutoSIM+AI mode) ---" >> "$LOG"

# Refresh AWS credentials
ada credentials update --account=XXXXXXXXXXXX --role=YourIAMRole --once --provider=conduit >> "$LOG" 2>&1

"$WASABI" \
  --prompt "TASK: Process AutoSIM-flagged tasks in the inflow room.

STEP 1: Use TaskeiListTasks with roomId YOUR-ROOM-UUID-HERE and workflowStep New - Inflow to get all open tasks.

STEP 2: For each task, use TaskeiGetTask to read its comments (commentLimit 5).

STEP 3: Check each task for AutoSIM comment markers:

  CASE A - Comment contains [ACTION:HOLD][VALIDATOR:AUTOSIM]:
    1. Use TaskeiUpdateTask to set workflowAction to Hold for Inflow Critieria Clarification
    2. Use TaskeiUpdateTask to post a READER-FRIENDLY comment using this EXACT format (replace placeholders with actual values):

COMMENT FORMAT FOR FAILURES:
---
[ACTION:HOLD][VALIDATOR:CRON]

🚨 **Inflow Validation Failed**

**Task:** TASKID — TASKNAME
**Severity:** HIGH/MEDIUM (X/8 fields have issues)
**Action:** Moved to Hold

---

**❌ Failed Fields:**

• **FieldName** — specific reason why it failed
• **FieldName** — specific reason why it failed

**✅ Passed Fields:**

• FieldName: value
• FieldName: value

---

**Next Steps:** Please fix the failed fields above and move task back to **New - Inflow**.

_— SIM Inflow Validator (AI)_
---
END OF COMMENT FORMAT

    3. Send Slack via curl: curl -s -X POST -H Content-Type:application/json -d '{\"text\":\"Inflow Validation Failed\nTask: TASKID - TASKNAME\nSeverity: X/8 fields failed\nAction: Moved to Hold\nhttps://taskei.example.com/tasks/TASKID\"}' https://hooks.slack.com/triggers/YOUR/WORKFLOW/WEBHOOK

  CASE B - Comment contains [ACTION:AI-REVIEW][VALIDATOR:AUTOSIM]:
    1. Analyze the task description using AI. Check for: gibberish text, invalid marketplaces, past dates (before June 2026), fake version numbers, vague summaries under 10 words, invalid environments, generic surface names.
    2. If AI finds issues: Use TaskeiUpdateTask to post comment using the SAME reader-friendly format above, AND set workflowAction to Hold for Inflow Critieria Clarification, AND send Slack.
    3. If AI passes: Do nothing (task stays in New-Inflow).

  CASE C - No AutoSIM marker in comments (backup validation):
    Run full 8-field validation (Summary, Build Details, Environment, Marketplace In Scope, Start & End Date, Test Priority, Surfaces, QA Unit/Smoke test). Same rules: placeholders/empty/vague refs without links/gibberish/invalid environments = FAIL. If fails: post comment using the SAME reader-friendly format above, set workflowAction to Hold, send Slack.

STEP 4: Skip any task that already has a comment containing -- SIM Inflow Validator from the cron (already processed). Also skip tasks already in Hold.

IMPORTANT RULES:
- P0 through P20 are ALL valid priorities
- NA = North America (valid marketplace)
- Valid environments: Beta, Gamma, Prod, UAT, Staging, Dev, Pre-prod, EVT, DVT, QA, SIT, Perf, Sandbox
- Valid surfaces: Android, iOS, Web, Kindle, Fire TV, mWeb, Desktop, Mobile
- Dates must be in the future (after June 2026) and include month

Do NOT ask questions. Execute immediately. Report count of tasks processed." \
  --non-interactive \
  --auto-accept-edits \
  --dangerously-accept-all-prompts \
  --no-history \
  --disable-continue \
  --skip-git-safety-check \
  >> "$LOG" 2>&1

echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] --- Cron: Done ---" >> "$LOG"
