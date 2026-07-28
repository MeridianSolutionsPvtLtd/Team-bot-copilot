import html

from azure.communication.email import EmailClient

from app.config import settings


def send_summary_email(attendees: list[str], meeting_title: str, summary_markdown: str) -> None:
    recipients = sorted({email.strip() for email in attendees if email and "@" in email})
    if not recipients:
        return

    client = EmailClient.from_connection_string(settings.acs_connection_string)
    safe_title = html.escape(meeting_title)
    safe_summary = html.escape(summary_markdown)

    message = {
        "senderAddress": settings.acs_email_from,
        "recipients": {
            "to": [{"address": email} for email in recipients],
        },
        "content": {
            "subject": f"Meeting Summary: {meeting_title}",
            "html": f"""
<html>
  <body>
    <p>Hello,</p>
    <p>Meeting summary for <strong>{safe_title}</strong> is below:</p>
    <pre style="white-space: pre-wrap; font-family: Segoe UI, Arial, sans-serif;">{safe_summary}</pre>
    <p>Regards,<br/>Meeting Intelligence Agent</p>
  </body>
</html>
""",
        },
    }

    poller = client.begin_send(message)
    result = poller.result()
    if result.get("status") not in {"Succeeded", "Running", "NotStarted"}:
        raise RuntimeError(f"ACS email send failed: {result}")
