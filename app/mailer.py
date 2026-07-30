import logging

from azure.communication.email import EmailClient

from app.config import settings
from app.email_template import build_html, build_plain_text
from app.timeutils import now_local_string

logger = logging.getLogger(__name__)


def send_summary_email(attendees: list[str], meeting_title: str, summary_markdown: str) -> None:
    recipients = sorted({email.strip() for email in attendees if email and "@" in email})
    if not recipients:
        logger.warning("No recipients resolved for '%s'; skipping email.", meeting_title)
        return

    generated_at = now_local_string()
    message = {
        "senderAddress": settings.acs_email_from,
        "recipients": {
            "to": [{"address": email} for email in recipients],
        },
        "content": {
            "subject": f"Meeting Summary: {meeting_title}",
            "plainText": build_plain_text(meeting_title, summary_markdown, generated_at),
            "html": build_html(meeting_title, summary_markdown, generated_at, len(recipients)),
        },
    }

    client = EmailClient.from_connection_string(settings.acs_connection_string)
    poller = client.begin_send(message)
    result = poller.result()
    if result.get("status") not in {"Succeeded", "Running", "NotStarted"}:
        raise RuntimeError(f"ACS email send failed: {result}")
    logger.info("Summary email sent to %d recipient(s) for '%s'.", len(recipients), meeting_title)
