# Pipeline Deployment Guide
## TestRail Webhook → Lambda → S3 Dashboard

---

## Step 1: Create S3 Bucket

```bash
aws s3 mb s3://testrail-analyzer-results --region us-east-1

# Enable static website hosting
aws s3 website s3://testrail-analyzer-results \
  --index-document index.html

# Set public read policy for dashboard (HTML files only)
aws s3api put-bucket-policy --bucket testrail-analyzer-results --policy '{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::testrail-analyzer-results/dashboard/*"
  }]
}'
```

---

## Step 2: Add S3 Permissions to Lambda Role

Add this policy to your existing Lambda role (`testrail-analyzer-v5-LambdaRole-iQa2Z8yMo5Ov`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::testrail-analyzer-results/*"
    }
  ]
}
```

---

## Step 3: Add Environment Variables to Lambda

```bash
aws lambda update-function-configuration \
  --function-name testrail-analyzer-v5-fn \
  --environment "Variables={
    TESTRAIL_URL=https://testrail.p2r.amazon.dev,
    TESTRAIL_EMAIL=your-email@example.com,
    TESTRAIL_KEY=YOUR_API_KEY,
    S3_BUCKET=testrail-analyzer-results,
    AI_ENDPOINT=https://b19n8vaa5g.execute-api.us-east-1.amazonaws.com/prod/analyze,
    AI_KEY=YOUR_AI_KEY
  }" \
  --region us-east-1
```

---

## Step 4: Add Webhook Route to API Gateway

```bash
# Add POST /webhook route
aws apigatewayv2 create-route \
  --api-id b19n8vaa5g \
  --route-key "POST /webhook" \
  --target integrations/YOUR_INTEGRATION_ID \
  --region us-east-1
```

Or via Console:
1. API Gateway → `b19n8vaa5g` → Routes
2. Create route: `POST /webhook`
3. Attach integration: same Lambda (`testrail-analyzer-v5-fn`)
4. Deploy to `prod` stage

---

## Step 5: Update Lambda Handler

Replace the Lambda code with `lambda_webhook.py` (or add routing logic):

```python
def lambda_handler(event, context):
    path = event.get("rawPath", "") or event.get("path", "")

    if "/webhook" in path:
        return webhook_handler(event, context)  # New pipeline handler
    elif "/analyze" in path:
        return analyze_handler(event, context)  # Existing AI handler
    elif "/bootstrap" in path:
        return bootstrap_handler(event, context)  # Existing bootstrap
```

---

## Step 6: Configure TestRail Webhook

1. Go to TestRail → **Administration** → **Integration** → **Webhooks**
2. Click **Add Webhook**
3. Configure:
   - **Name:** `Automation Analyzer`
   - **URL:** `https://b19n8vaa5g.execute-api.us-east-1.amazonaws.com/prod/webhook`
   - **Events:** ☑ Case Created, ☑ Case Updated
   - **Projects:** Select your project(s)
4. Click **Save**

> ⚠️ If your TestRail instance doesn't support webhooks, use the scheduled alternative (see below).

---

## Step 7: Verify

### Test manually:
```bash
curl -X POST https://b19n8vaa5g.execute-api.us-east-1.amazonaws.com/prod/webhook \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_API_KEY" \
  -d '{"event": "case_created", "case_id": 4371462}'
```

### Expected response:
```json
{
  "status": "analyzed",
  "case_id": 4371462,
  "label": "Partially Automatable",
  "score": 28,
  "dashboard": "https://testrail-analyzer-results.s3.amazonaws.com/dashboard/A11y_regression/index.html"
}
```

### View dashboard:
Open the `dashboard` URL in browser — live-updating HTML page.

---

## Alternative: Scheduled Scan (if webhooks not available)

If TestRail admin can't enable webhooks, use CloudWatch Events:

```bash
# Create rule to run daily at 2 AM UTC
aws events put-rule \
  --name "testrail-daily-scan" \
  --schedule-expression "cron(0 2 * * ? *)" \
  --region us-east-1

# Target the Lambda with a full_scan payload
aws events put-targets \
  --rule "testrail-daily-scan" \
  --targets "Id=1,Arn=arn:aws:lambda:us-east-1:XXXXXXXXXXXX:function:testrail-analyzer-v5-fn,Input={\"action\":\"full_scan\",\"project_id\":123}" \
  --region us-east-1
```

---

## Dashboard URL Pattern

```
https://testrail-analyzer-results.s3.amazonaws.com/dashboard/{PROJECT_NAME}/index.html
```

Example:
```
https://testrail-analyzer-results.s3.amazonaws.com/dashboard/A11y_regression/index.html
```

---

## Architecture Summary

```
TestRail                    AWS (XXXXXXXXXXXX, us-east-1)
┌──────────────┐           ┌─────────────────────────────────────┐
│ TC Created   │──webhook─▶│ API Gateway (POST /webhook)          │
│ TC Updated   │           │       │                              │
└──────────────┘           │       ▼                              │
                           │ Lambda (testrail-analyzer-v5-fn)     │
                           │   1. Parse webhook                   │
                           │   2. Fetch TC from TestRail API      │
                           │   3. Heuristic score (instant)       │
                           │   4. AI analysis (optional)          │
                           │   5. Store result → S3               │
                           │   6. Regenerate dashboard → S3       │
                           │       │                              │
                           │       ▼                              │
                           │ S3 (testrail-analyzer-results)       │
                           │   /results/{project}/{tc_id}.json    │
                           │   /dashboard/{project}/index.html    │
                           │   /dashboard/{project}/data.json     │
                           └─────────────────────────────────────┘
                                    │
                                    ▼
                           Team views dashboard URL
                           (auto-updates on each webhook)
```

---

## Cost Estimate

| Component | Cost per webhook trigger |
|-----------|------------------------|
| Lambda | ~$0.000002 |
| S3 PUT (3 objects) | ~$0.000015 |
| API Gateway | ~$0.0000035 |
| AI (optional) | ~$0.008 |
| **Total per TC** | **~$0.008** (with AI) or **~$0.00** (heuristic only) |

For 100 new TCs/month: **~$0.80/month** with AI, essentially free without.
