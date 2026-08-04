import json
import logging
import re
import threading
import time

from fastapi import APIRouter, Request, Response

from app.config import settings
from app.db import (
    is_processed,
    mark_email_sent,
    mark_processed,
    marker_email_already_sent,
    release_processing_claim,
    try_claim_processing,
)
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
    logger.info(
        "PROCESS start meeting_id=%s transcript_id=%s user_id=%s",
        parsed.meeting_id,
        parsed.transcript_id,
        parsed.user_id,
    )
    claim_id = try_claim_processing(
        parsed.transcript_id,
        parsed.meeting_id,
        organizer_user_id=parsed.user_id,
    )
    if not claim_id:
        logger.warning(
            "PROCESS skipped — could not claim lock for transcript_id=%s (already processing/done or missing organizer).",
            parsed.transcript_id,
        )
        return

    logger.info("PROCESS claimed transcript_id=%s claim_id=%s", parsed.transcript_id, claim_id)
    claimed = True
    try:
        logger.info("PROCESS fetching meeting details...")
        meeting = get_meeting_details(parsed.meeting_id, parsed.user_id)
        meeting_title = meeting.get("subject") or "Microsoft Teams Meeting"
        logger.info("PROCESS meeting title='%s'", meeting_title)

        logger.info("PROCESS fetching transcript content...")
        transcript = get_transcript_content(parsed.meeting_id, parsed.transcript_id, parsed.user_id)
        logger.info("PROCESS transcript fetched chars=%d", len(transcript or ""))

        logger.info("PROCESS summarizing with Azure OpenAI...")
        summary = summarize_transcript(meeting_title, transcript)

        logger.info("PROCESS fetching attendance + calendar recipients...")
        attendance_records = _fetch_attendance_records(parsed)
        calendar_event = get_calendar_event(meeting, parsed.user_id)
        emails = _collect_recipients(meeting, attendance_records, calendar_event)

        logger.info(
            "PROCESS recipients for '%s': attendance=%d calendar_attendees=%d final=%d list=%s",
            meeting_title,
            len(attendance_records),
            len((calendar_event or {}).get("attendees") or []),
            len(emails),
            ", ".join(emails) or "(none)",
        )

        # Summaries first, then done marker — never mark done if hard writes fail.
        logger.info("PROCESS writing summaries to OneDrive...")
        stored = mark_processed(
            parsed.transcript_id,
            parsed.meeting_id,
            summary,
            meeting_title=meeting_title,
            attendee_emails=emails,
            organizer_user_id=parsed.user_id,
            claim_id=claim_id,
        )
        if not stored:
            logger.error(
                "PROCESS aborted — OneDrive mark_processed failed for transcript_id=%s",
                parsed.transcript_id,
            )
            release_processing_claim(
                parsed.transcript_id,
                claim_id,
                organizer_user_id=parsed.user_id,
            )
            claimed = False
            return

        logger.info("PROCESS OneDrive storage completed for transcript_id=%s", parsed.transcript_id)
        # Done marker is durable now; don't delete it if email fails.
        claimed = False

        if emails and not marker_email_already_sent(
            parsed.transcript_id,
            organizer_user_id=parsed.user_id,
        ):
            logger.info("PROCESS sending summary email...")
            send_summary_email(emails, meeting_title, summary)
            try:
                mark_email_sent(
                    parsed.transcript_id,
                    claim_id,
                    organizer_user_id=parsed.user_id,
                )
                logger.info("PROCESS email_sent flag persisted.")
            except Exception:
                # Mail already left ACS; persist failure may allow one rare duplicate on retry.
                logger.exception(
                    "Summary email sent for %s but failed to persist email_sent flag.",
                    parsed.transcript_id,
                )
        else:
            logger.info(
                "PROCESS skipping email (no recipients or already marked email_sent) transcript_id=%s",
                parsed.transcript_id,
            )

        logger.info("PROCESS success transcript_id=%s meeting='%s'", parsed.transcript_id, meeting_title)
    except Exception:
        logger.exception("Failed to process transcript event for meeting %s", parsed.meeting_id)
        if claimed:
            release_processing_claim(
                parsed.transcript_id,
                claim_id,
                organizer_user_id=parsed.user_id,
            )
    finally:
        with _inflight_lock:
            _inflight_transcripts.discard(parsed.transcript_id)
        logger.info("PROCESS finished (thread cleanup) transcript_id=%s", parsed.transcript_id)


def _queue_transcript(parsed: ParsedResource) -> None:
    """Graph expects the webhook to answer within seconds, so do the work off-thread."""
    with _inflight_lock:
        if parsed.transcript_id in _inflight_transcripts:
            logger.info(
                "QUEUE skip — transcript already in-flight: %s",
                parsed.transcript_id,
            )
            return
        _inflight_transcripts.add(parsed.transcript_id)
    logger.info(
        "QUEUE starting background thread for transcript_id=%s meeting_id=%s",
        parsed.transcript_id,
        parsed.meeting_id,
    )
    threading.Thread(target=_process_transcript, args=(parsed,), daemon=True).start()


@router.get("/webhook")
@router.post("/webhook")
async def graph_webhook(request: Request):
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        logger.info("WEBHOOK validation challenge received — echoing token.")
        return Response(content=validation_token, media_type="text/plain", status_code=200)

    if request.method == "GET":
        logger.info("WEBHOOK GET probe — endpoint active.")
        return Response(content="Webhook endpoint is active.", media_type="text/plain", status_code=200)

    raw_body = await request.body()
    logger.info(
        "WEBHOOK POST received bytes=%d content_type=%s",
        len(raw_body),
        request.headers.get("content-type"),
    )
    if not raw_body.strip():
        logger.info("WEBHOOK empty body — returning 202.")
        return Response(content="", status_code=202)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("WEBHOOK non-JSON body — returning 202. preview=%r", raw_body[:200])
        return Response(content="", status_code=202)

    if payload.get("lifecycleEvent"):
        logger.info("WEBHOOK lifecycle notification: %s", payload.get("lifecycleEvent"))
        return Response(content="", status_code=202)

    notifications = payload.get("value", [])
    if not isinstance(notifications, list):
        logger.warning("WEBHOOK unexpected payload keys=%s", list(payload.keys()))
        return Response(content="", status_code=202)

    logger.info("WEBHOOK notification batch size=%d", len(notifications))
    for index, item in enumerate(notifications):
        client_state = item.get("clientState")
        resource = item.get("resource", "")
        change_type = item.get("changeType")
        logger.info(
            "WEBHOOK[%d] changeType=%s resource=%s clientState_match=%s",
            index,
            change_type,
            resource[:250],
            client_state == settings.client_state,
        )
        if client_state != settings.client_state:
            logger.warning(
                "WEBHOOK[%d] skipped — clientState mismatch (got=%r).",
                index,
                (client_state or "")[:40],
            )
            continue

        parsed = parse_graph_resource(resource)
        if not parsed:
            logger.warning("WEBHOOK[%d] skipped — resource parse failed.", index)
            continue

        if is_processed(parsed.transcript_id, organizer_user_id=parsed.user_id):
            logger.info(
                "WEBHOOK[%d] skipped — already processed/blocked transcript_id=%s user_id=%s",
                index,
                parsed.transcript_id,
                parsed.user_id,
            )
            continue

        _queue_transcript(parsed)

    return Response(content="", status_code=202)
