from fastapi import APIRouter, Request, Response

from app.config import settings
from app.db import is_processed, mark_processed
from app.graph import get_meeting_details, get_transcript_content
from app.mailer import send_summary_email
from app.parser import parse_graph_resource
from app.summarizer import summarize_transcript

router = APIRouter()


def _extract_attendee_emails(meeting_details: dict) -> list[str]:
    attendees = meeting_details.get("participants", {}).get("attendees", [])
    emails: list[str] = []
    for attendee in attendees:
        identity = attendee.get("identity", {})
        user = identity.get("user", {})
        email = attendee.get("upn") or user.get("id") or user.get("displayName")
        if email and "@" in email:
            emails.append(email)
    organizer = meeting_details.get("participants", {}).get("organizer", {})
    org_user = organizer.get("identity", {}).get("user", {})
    organizer_upn = organizer.get("upn") or org_user.get("id")
    if organizer_upn and "@" in organizer_upn:
        emails.append(organizer_upn)
    return list(set(emails))


@router.post("/webhook")
async def graph_webhook(request: Request):
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        return Response(content=validation_token, media_type="text/plain", status_code=200)

    payload = await request.json()
    notifications = payload.get("value", [])

    for item in notifications:
        if item.get("clientState") != settings.client_state:
            continue

        parsed = parse_graph_resource(item.get("resource", ""))
        if not parsed:
            continue

        if is_processed(parsed.transcript_id):
            continue

        try:
            meeting = get_meeting_details(parsed.meeting_id, parsed.user_id)
            transcript = get_transcript_content(parsed.meeting_id, parsed.transcript_id, parsed.user_id)
            meeting_title = meeting.get("subject", "Microsoft Teams Meeting")

            summary = summarize_transcript(meeting_title, transcript)
            emails = _extract_attendee_emails(meeting)
            send_summary_email(emails, meeting_title, summary)

            mark_processed(
                parsed.transcript_id,
                parsed.meeting_id,
                summary,
                meeting_title=meeting_title,
                attendee_emails=emails,
            )
        except Exception:
            # Return accepted so Graph does not continuously retry batch;
            # production apps should also push failures to a queue/dead-letter store.
            continue

    return {"status": "accepted"}
