"""
SIM Inflow Validator - Lambda (AI + Move + Slack)
Picks up tasks flagged by AutoSIM via comment markers:
  [ACTION:HOLD] = move to Hold + Slack
  [ACTION:AI-REVIEW] = AI analysis + maybe Hold + Slack
"""
import json
import os
import urllib3
import boto3
from datetime import datetime, timezone

http = urllib3.PoolManager()
TASKEI_BASE = 'https://taskei.example.com/api/v1'
ROOM_ID = 'YOUR-ROOM-UUID-HERE'
SLACK_WEBHOOK = 'https://hooks.slack.com/services/YOUR/WEBHOOK/HERE'
HOLD_STEP = 'Hold for Inflow Critieria Clarification'
TABLE_NAME = 'your-dynamodb-table'

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(TABLE_NAME)
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')


def lambda_handler(event, context):
    """Main handler - query tasks in New-Inflow, check for AutoSIM markers, act."""

    # Get tasks in "New - Inflow" step
    tasks = get_tasks_in_step('New - Inflow')

    processed = 0
    moved = 0
    ai_reviewed = 0

    for task in tasks:
        task_id = task.get('shortId') or task.get('id')

        # Check if already processed
        if is_processed(task_id):
            continue

        # Get task comments
        comments = get_task_comments(task_id)

        # Check for AutoSIM markers
        action = None
        for comment in comments:
            body = comment.get('body', '')
            if '[ACTION:HOLD][VALIDATOR:AUTOSIM]' in body:
                action = 'hold'
                break
            elif '[ACTION:AI-REVIEW][VALIDATOR:AUTOSIM]' in body:
                action = 'ai-review'
                break

        if not action:
            continue  # No AutoSIM marker, skip

        if action == 'hold':
            # Move to Hold + Slack
            move_to_hold(task_id)
            send_slack_notification(task, comments)
            mark_processed(task_id, 'hold')
            moved += 1

        elif action == 'ai-review':
            # AI analysis
            ai_result = run_ai_analysis(task)
            if ai_result['failed']:
                # AI found issues - add comment + move + Slack
                add_ai_comment(task_id, ai_result)
                move_to_hold(task_id)
                send_slack_ai_notification(task, ai_result)
                mark_processed(task_id, 'ai-failed')
            else:
                # AI passed - just mark processed
                mark_processed(task_id, 'ai-passed')
            ai_reviewed += 1

        processed += 1

    return {
        'statusCode': 200,
        'body': json.dumps({
            'tasks_checked': len(tasks),
            'processed': processed,
            'moved_to_hold': moved,
            'ai_reviewed': ai_reviewed
        })
    }


def get_tasks_in_step(step_name):
    """Query Taskei for tasks in a specific workflow step."""
    url = f'{TASKEI_BASE}/rooms/{ROOM_ID}/tasks?workflowStep={step_name}&status=Open&maxResults=50'
    resp = http.request('GET', url, headers=get_headers())
    if resp.status == 200:
        data = json.loads(resp.data.decode('utf-8'))
        return data.get('tasks', data.get('results', []))
    return []


def get_task_comments(task_id):
    """Get recent comments for a task."""
    url = f'{TASKEI_BASE}/tasks/{task_id}/comments?limit=10'
    resp = http.request('GET', url, headers=get_headers())
    if resp.status == 200:
        data = json.loads(resp.data.decode('utf-8'))
        return data.get('comments', data.get('results', []))
    return []


def move_to_hold(task_id):
    """Move task to Hold workflow step."""
    url = f'{TASKEI_BASE}/tasks/{task_id}'
    payload = json.dumps({'workflowAction': HOLD_STEP})
    resp = http.request('PUT', url, body=payload, headers=get_headers())
    return resp.status == 200


def add_ai_comment(task_id, ai_result):
    """Add AI analysis comment to task."""
    msg = '[AI-ANALYSIS] Content Quality Review\n\n'
    msg += 'AI found the following issues:\n'
    for issue in ai_result.get('issues', []):
        msg += f'  [!] {issue}\n'
    msg += '\nPlease address these and move back to New-Inflow.\n-- SIM Inflow Validator (AI)'

    url = f'{TASKEI_BASE}/tasks/{task_id}/comments'
    payload = json.dumps({'body': msg})
    http.request('POST', url, body=payload, headers=get_headers())


def run_ai_analysis(task):
    """Run Bedrock AI analysis on task content."""
    description = task.get('description', '')
    title = task.get('name', task.get('title', ''))

    prompt = f"""Analyze this task submission for quality issues. Check for:
1. Gibberish or random text in any field (like "dwed33qgf")
2. Invalid marketplace names (valid: US, UK, DE, FR, IT, ES, JP, IN, CA, MX, BR, AU, NZ, NL, PL, SE, BE, AE, SA, EG, SG, NA, India, Japan, EMEA, Europe, APAC, Asia, LATAM, ROW, Global)
3. Dates that are in the past or obviously fake
4. Build details that don't contain a real version number
5. Summary that is too vague (less than 10 words with no specifics)
6. Environment must be real: Beta, Gamma, Prod, UAT, Staging, Dev, Pre-prod

Task Title: {title}
Task Description:
{description}

Respond in JSON format:
{{"passed": true/false, "issues": ["issue 1", "issue 2"]}}
Only flag CLEAR problems. If content looks reasonable, pass it."""

    try:
        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-5-haiku-20241022-v1:0',
            body=json.dumps({
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': 300,
                'messages': [{'role': 'user', 'content': prompt}]
            })
        )
        result = json.loads(response['body'].read())
        ai_text = result['content'][0]['text']
        ai_json = json.loads(ai_text)
        return {
            'failed': not ai_json.get('passed', True),
            'issues': ai_json.get('issues', [])
        }
    except Exception as e:
        print(f'AI analysis error: {e}')
        return {'failed': False, 'issues': []}


def send_slack_notification(task, comments):
    """Send Slack notification for basic validation failure."""
    task_id = task.get('shortId') or task.get('id')
    title = (task.get('name', '') or task.get('title', ''))[:60]
    link = f'https://taskei.example.com/tasks/{task_id}'

    msg = f'*Inflow Validation Failed*\n*Task:* <{link}|{task_id}> - {title}\n*Action:* Moved to Hold\n*Source:* AutoSIM + Lambda'

    payload = json.dumps({'text': msg})
    http.request('POST', SLACK_WEBHOOK, body=payload, headers={'Content-Type': 'application/json'})


def send_slack_ai_notification(task, ai_result):
    """Send Slack notification for AI validation failure."""
    task_id = task.get('shortId') or task.get('id')
    title = (task.get('name', '') or task.get('title', ''))[:60]
    link = f'https://taskei.example.com/tasks/{task_id}'

    issues = '\n'.join([f'  - {i}' for i in ai_result.get('issues', [])])
    msg = f'*AI Content Review Failed*\n*Task:* <{link}|{task_id}> - {title}\n*Action:* Moved to Hold\n*AI Issues:*\n{issues}'

    payload = json.dumps({'text': msg})
    http.request('POST', SLACK_WEBHOOK, body=payload, headers={'Content-Type': 'application/json'})


def is_processed(task_id):
    """Check if task was already processed."""
    try:
        resp = table.get_item(Key={'task_id': str(task_id)})
        return 'Item' in resp
    except Exception:
        return False


def mark_processed(task_id, action):
    """Mark task as processed in DynamoDB."""
    table.put_item(Item={
        'task_id': str(task_id),
        'action': action,
        'processed_at': datetime.now(timezone.utc).isoformat()
    })


def get_headers():
    """Get auth headers for Taskei API."""
    return {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
