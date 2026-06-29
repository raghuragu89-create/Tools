"""
Sends the HTML report via SMTP (with TLS) or AWS SES.
Credentials are read from environment variables with fallback to config values.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List


def send_via_smtp(
    html_body: str,
    subject: str,
    sender: str,
    recipients: List[str],
    smtp_host: str,
    smtp_port: int,
    use_tls: bool = True,
    username: str = "",
    password: str = "",
) -> bool:
    """Send HTML email via SMTP. Returns True on success."""
    user = username or os.environ.get("SMTP_USER", "")
    pwd  = password or os.environ.get("SMTP_PASS", "")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if use_tls:
            # STARTTLS on port 587
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if user and pwd:
                    server.login(user, pwd)
                server.sendmail(sender, recipients, msg.as_string())
        elif smtp_port == 465:
            # Implicit SSL on port 465
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                if user and pwd:
                    server.login(user, pwd)
                server.sendmail(sender, recipients, msg.as_string())
        else:
            # Plain SMTP (no encryption) — for internal relays
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                if user and pwd:
                    server.login(user, pwd)
                server.sendmail(sender, recipients, msg.as_string())
        return True
    except Exception as e:
        print(f"[email] SMTP error: {e}")
        return False


def send_via_ses(
    html_body: str,
    subject: str,
    sender: str,
    recipients: List[str],
    region: str = "us-east-1",
) -> bool:
    """Send HTML email via AWS SES using boto3. Returns True on success."""
    try:
        import boto3
    except ImportError:
        print("[email] boto3 not installed — cannot use SES. Install with: pip install boto3")
        return False

    ses_region = region or os.environ.get("AWS_SES_REGION", "us-east-1")
    client = boto3.client("ses", region_name=ses_region)

    try:
        client.send_email(
            Source=sender,
            Destination={"ToAddresses": recipients},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            },
        )
        return True
    except Exception as e:
        print(f"[email] SES error: {e}")
        return False
