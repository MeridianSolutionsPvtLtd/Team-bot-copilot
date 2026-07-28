from app.config import settings
from app.graph import _request


def send_summary_email(attendees: list[str], meeting_title: str, summary_markdown: str) -> None:
    recipients = [{"emailAddress": {"address": email}} for email in sorted(set(attendees)) if email]
    if not recipients:
        return

    html_content = f"""
<html>
  <body>
    <p>Hello,</p>
    <p>Meeting summary for <strong>{meeting_title}</strong> is below:</p>
    <pre style="white-space: pre-wrap; font-family: Segoe UI, Arial, sans-serif;">{summary_markdown}</pre>
    <p>Regards,<br/>Meeting Intelligence Agent</p>
  </body>
</html>
"""
    payload = {
        "message": {
            "subject": f"Meeting Summary: {meeting_title}",
            "body": {"contentType": "HTML", "content": html_content},
            "toRecipients": recipients,
        },
        "saveToSentItems": "true",
    }
    _request("POST", f"https://graph.microsoft.com/v1.0/users/{settings.mail_from}/sendMail", json=payload)
