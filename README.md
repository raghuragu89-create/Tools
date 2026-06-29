# QA Automation Tools Suite

A collection of automation tools built for QA teams to improve efficiency, reduce manual effort, and maintain lab/test infrastructure.

## Tools

### 1. [TestRail Analyzer Suite](./testrail-analyzer-suite/)
AI-powered automation feasibility analysis and test optimization tool.
- Analyzes test cases for automation potential (heuristic + AI scoring)
- Generates Excel + HTML reports with per-case recommendations
- Detects duplicates, redundancy, missing steps
- Maps test cases to recommended automation frameworks
- **Cost:** $0 (runs locally)
- **Saves:** 4-6 hours/week

### 2. [SIM Inflow Validator](./sim-inflow-validator/)
Automated task intake quality gate for project management (Taskei/SIM).
- Validates mandatory fields in task submissions
- AI-powered content quality analysis (gibberish, vague refs, invalid data)
- Instant notifications via Slack + task comments
- Auto-moves non-compliant tasks to Hold
- **Cost:** ~$35/year per room
- **Saves:** 2-4 hours/week

### 3. [Lab Maintenance Tool](./lab-maintenance-tool/)
Automated daily lab health checks with email reporting.
- Pings machines, checks ACME status, verifies device connectivity
- Battery, Wi-Fi, book availability, account verification
- KRAFT Device Farm dashboard integration
- iOS Xcode device pairing checks
- Weekly automated device restart
- **Cost:** $0 (runs locally)
- **Saves:** 3-4 hours/week

## Total Impact
- **Weekly hours saved:** ~10-14 hours
- **Annual cost:** ~$35 total (only SIM Validator has cloud costs)

## Setup

Each tool has its own README with setup instructions. General requirements:
- Python 3.10+
- Network access to relevant services (TestRail, lab machines, etc.)

## License

Internal use only. Not for redistribution.
