import json
import logging
import re
import threading
import time

from fastapi import APIRouter, Request, Response

from app.config import settings
from app.db import is_processed, mark_processed
from app.graph import (
    get_attendance_records,
    get_calendar_event,
    get_meeting_details,
    get_transcript_content,
)
from app.mailer import send_summary_email
from app.parser import ParsedResource, parse_graph_resource
from app.summarizer import summarize_transcript

logger = logging.getLogger(__name__)

router = APIRouter()

# Attendance reports are generated a little after the meeting ends, sometimes later
# than the transcript notification, so give Graph a few chances to catch up.
ATTENDANCE_ATTEMPTS = 4
ATTENDANCE_RETRY_SECONDS = 20

_inflight_lock = threading.Lock()
_inflight_transcripts: set[str] = set()


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _emails_from_identity_blob(blob: dict) -> list[str]:
    """Pull anything that looks like an address out of a Graph identity/participant object."""
    found: list[str] = []
    for key in ("upn", "emailAddress", "email", "address", "id", "displayName"):
        value = blob.get(key)
        if isinstance(value, str) and EMAIL_PATTERN.match(value.strip()):
            found.append(value.strip())
        elif isinstance(value, dict):
            found.extend(_emails_from_identity_blob(value))

    identity = blob.get("identity")
    if isinstance(identity, dict):
        for entry in identity.values():
            if isinstance(entry, dict):
                found.extend(_emails_from_identity_blob(entry))
    return found


def _collect_recipients(
    meeting_details: dict,
    attendance_records: list[dict],
    calendar_event: dict | None,
) -> list[str]:
    emails: list[str] = []

    for record in attendance_records:
        emails.extend(_emails_from_identity_blob(record))

    participants = meeting_details.get("participants") or {}
    for attendee in participants.get("attendees") or []:
        emails.extend(_emails_from_identity_blob(attendee))
    organizer = participants.get("organizer") or {}
    emails.extend(_emails_from_identity_blob(organizer))

    if calendar_event:
        for attendee in calendar_event.get("attendees") or []:
            emails.extend(_emails_from_identity_blob(attendee))
        emails.extend(_emails_from_identity_blob(calendar_event.get("organizer") or {}))

    return sorted({email.lower() for email in emails})


def _fetch_attendance_records(parsed: ParsedResource) -> list[dict]:
    for attempt in range(1, ATTENDANCE_ATTEMPTS + 1):
        records = get_attendance_records(parsed.meeting_id, parsed.user_id)
        if records is None:
            # Graph refused the call, so retrying will not help.
            return []
        if records:
            logger.info("Attendance report returned %d record(s) on attempt %d.", len(records), attempt)
            return records
        if attempt < ATTENDANCE_ATTEMPTS:
            time.sleep(ATTENDANCE_RETRY_SECONDS)
    logger.warning("No attendance records available yet for meeting %s.", parsed.meeting_id)
    return []


def _process_transcript(parsed: ParsedResource) -> None:
    try:
        meeting = get_meeting_details(parsed.meeting_id, parsed.user_id)
        transcript = get_transcript_content(parsed.meeting_id, parsed.transcript_id, parsed.user_id)
        meeting_title = meeting.get("subject") or "Microsoft Teams Meeting"

        summary = summarize_transcript(meeting_title, transcript)

        attendance_records = _fetch_attendance_records(parsed)
        calendar_event = get_calendar_event(meeting, parsed.user_id)
        emails = _collect_recipients(meeting, attendance_records, calendar_event)

        logger.info(
            "Recipients for '%s': %d from attendance, %d invited on calendar, final list: %s",
            meeting_title,
            len(attendance_records),
            len((calendar_event or {}).get("attendees") or []),
            ", ".join(emails) or "(none)",
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
        logger.exception("Failed to process transcript event for meeting %s", parsed.meeting_id)
    finally:
        with _inflight_lock:
            _inflight_transcripts.discard(parsed.transcript_id)


def _queue_transcript(parsed: ParsedResource) -> None:
    """Graph expects the webhook to answer within seconds, so do the work off-thread."""
    with _inflight_lock:
        if parsed.transcript_id in _inflight_transcripts:
            return
        _inflight_transcripts.add(parsed.transcript_id)
    threading.Thread(target=_process_transcript, args=(parsed,), daemon=True).start()


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

        _queue_transcript(parsed)

    return Response(content="", status_code=202)
