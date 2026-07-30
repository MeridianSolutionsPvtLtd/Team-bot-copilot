import json
import logging

from fastapi import APIRouter, Request, Response

from app.config import settings
from app.db import is_processed, mark_processed
from app.graph import get_attendance_records, get_meeting_details, get_transcript_content
from app.mailer import send_summary_email
from app.parser import parse_graph_resource
from app.summarizer import summarize_transcript

logger = logging.getLogger(__name__)

router = APIRouter()


def _emails_from_participant(participant: dict) -> list[str]:
    identity = participant.get("identity") or {}
    candidates = [participant.get("upn")]
    # Guests and external users expose their address under different identity types.
    for identity_type in ("user", "guest", "externalUser", "encrypted"):
        entry = identity.get(identity_type) or {}
        if isinstance(entry, dict):
            candidates.extend([entry.get("id"), entry.get("displayName"), entry.get("email")])
    return [value for value in candidates if isinstance(value, str) and "@" in value]


def _extract_attendee_emails(meeting_details: dict, attendance_records: list[dict]) -> list[str]:
    emails: list[str] = []

    for record in attendance_records:
        email = record.get("emailAddress")
        if isinstance(email, str) and "@" in email:
            emails.append(email)
        emails.extend(_emails_from_participant(record))

    participants = meeting_details.get("participants") or {}
    for attendee in participants.get("attendees") or []:
        emails.extend(_emails_from_participant(attendee))

    organizer = participants.get("organizer") or {}
    emails.extend(_emails_from_participant(organizer))

    return sorted({email.strip().lower() for email in emails})


@router.get("/webhook")
@router.post("/webhook")
async def graph_webhook(request: Request):
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        return Response(content=validation_token, media_type="text/plain", status_code=200)

    if request.method == "GET":
        return Response(content="Webhook endpoint is active.", media_type="text/plain", status_code=200)

    raw_body = await request.body()
    if not raw_body.strip():
        logger.info("Received empty webhook POST body.")
        return Response(content="", status_code=202)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("Received non-JSON webhook POST body.")
        return Response(content="", status_code=202)

    if payload.get("lifecycleEvent"):
        logger.info("Received lifecycle notification: %s", payload.get("lifecycleEvent"))
        return Response(content="", status_code=202)

    notifications = payload.get("value", [])
    if not isinstance(notifications, list):
        logger.warning("Unexpected webhook payload format.")
        return Response(content="", status_code=202)

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

            attendance_records = get_attendance_records(parsed.meeting_id, parsed.user_id)
            emails = _extract_attendee_emails(meeting, attendance_records)
            logger.info(
                "Resolved %d recipient(s) for meeting %s: %s",
                len(emails),
                parsed.meeting_id,
                ", ".join(emails),
            )

            send_summary_email(emails, meeting_title, summary)

            mark_processed(
                parsed.transcript_id,
                parsed.meeting_id,
                summary,
                meeting_title=meeting_title,
                attendee_emails=emails,
            )
        except Exception:
            logger.exception(
                "Failed to process transcript event for meeting %s",
                parsed.meeting_id,
            )
            continue

    return Response(content="", status_code=202)
