"""
TestRail Analyzer — Per-Team API Key Generator
Creates separate API Gateway usage plans + keys for each team.
Prevents 429 rate limiting across teams.

Run from AWS CloudShell or any machine with AWS CLI credentials.
Usage: python create_team_keys.py
"""

import json
import boto3

# Config
API_ID = "b19n8vaa5g"
STAGE = "prod"
REGION = "us-east-1"

# Teams to create keys for (add your teams here)
TEAMS = [
    {"name": "KRQ", "rate_limit": 15, "burst": 20, "daily_quota": 6000},
    {"name": "A11y", "rate_limit": 15, "burst": 20, "daily_quota": 6000},
    {"name": "DPPUI", "rate_limit": 15, "burst": 20, "daily_quota": 6000},
    {"name": "Shared", "rate_limit": 10, "burst": 15, "daily_quota": 4000},
]

apigw = boto3.client("apigateway", region_name=REGION)


def create_team_key(team):
    name = team["name"]
    print(f"\n{'='*50}")
    print(f"Creating usage plan + API key for team: {name}")

    # 1. Create Usage Plan
    usage_plan = apigw.create_usage_plan(
        name=f"TestRailAnalyzer-{name}",
        description=f"API usage plan for {name} team - TestRail Analyzer",
        apiStages=[{"apiId": API_ID, "stage": STAGE}],
        throttle={"rateLimit": team["rate_limit"], "burstLimit": team["burst"]},
        quota={"limit": team["daily_quota"], "period": "DAY"},
    )
    plan_id = usage_plan["id"]
    print(f"  Usage Plan created: {plan_id}")

    # 2. Create API Key
    api_key = apigw.create_api_key(
        name=f"TestRailAnalyzer-{name}-Key",
        description=f"API key for {name} team",
        enabled=True,
    )
    key_id = api_key["id"]
    key_value = api_key["value"]
    print(f"  API Key created: {key_id}")
    print(f"  Key Value: {key_value}")

    # 3. Associate key with usage plan
    apigw.create_usage_plan_key(
        usagePlanId=plan_id,
        keyId=key_id,
        keyType="API_KEY",
    )
    print(f"  Key associated with plan ✓")

    return {
        "team": name,
        "usage_plan_id": plan_id,
        "api_key_id": key_id,
        "api_key_value": key_value,
        "daily_quota": team["daily_quota"],
        "rate_limit": team["rate_limit"],
    }


def main():
    print("TestRail Analyzer — Per-Team API Key Generator")
    print(f"API Gateway: {API_ID} | Stage: {STAGE} | Region: {REGION}")

    results = []
    for team in TEAMS:
        try:
            result = create_team_key(team)
            results.append(result)
        except Exception as e:
            print(f"  ERROR: {e}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY — Distribute these keys to each team:")
    print(f"{'='*60}")
    print(f"{'Team':<10} {'Daily Quota':<12} {'Rate':<8} {'API Key'}")
    print(f"{'-'*10} {'-'*12} {'-'*8} {'-'*40}")
    for r in results:
        print(f"{r['team']:<10} {r['daily_quota']:<12} {r['rate_limit']:<8} {r['api_key_value']}")

    print(f"\n{'='*60}")
    print("NEXT STEPS:")
    print("1. Give each team their API key")
    print("2. Team configures key in tool: AI & KB panel → Edit → AI Key")
    print("3. Each team has independent quota — no shared blocking")
    print(f"{'='*60}")

    # Save to file
    with open("team_keys.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved to team_keys.json")


if __name__ == "__main__":
    main()
