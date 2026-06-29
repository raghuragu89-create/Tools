import smtplib
from email.mime.text import MIMEText

msg = MIMEText('Test email from TestRail Analyzer Pipeline.\n\nIf you see this, email notifications are working!')
msg['From'] = 'your-email@example.com'
msg['To'] = 'your-email@example.com'
msg['Subject'] = '[Test] TestRail Analyzer Pipeline Email'

try:
    with smtplib.SMTP('smtp.your-provider.com', 25, timeout=10) as server:
        server.sendmail('your-email@example.com', ['your-email@example.com'], msg.as_string())
    print('SUCCESS! Check your inbox.')
except Exception as e:
    print(f'FAILED: {e}')
