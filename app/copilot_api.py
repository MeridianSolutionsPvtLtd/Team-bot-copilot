from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import settings
from app.db import get_by_meeting_id, list_recent, search_by_title, user_can_access
from app.mailer import send_summary_email

router = APIRouter()


def verify_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.copilot_api_key:
        raise HTTPException(status_code=503, detail="Copilot API key not configured.")
    if x_api_key != settings.copilot_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key.")


def resolve_caller(
    x_user_email: str = Header(default="", alias="X-User-Email"),
) -> dict:
    """Identify the Teams user asking Copilot.

    Copilot Studio must pass System.User.Email as the X-User-Email header on
    every HTTP action. Without it we refuse the call so summaries cannot leak
    across the organization through the shared API key alone.
    """
    email = (x_user_email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(
            status_code=400,
            detail="X-User-Email header is required. Pass System.User.Email from Copilot Studio.",
        )
    return {
        "email": email,
        "is_admin": email in settings.admin_email_set(),
    }


def _meeting_card(meeting: dict) -> dict:
    return {
        "meeting_id": meeting["meeting_id"],
        "meeting_title": meeting["meeting_title"],
        "created_at": meeting["created_at"],
        "created_at_local": meeting["created_at_local"],
    }


@router.get("/meetings/recent", dependencies=[Depends(verify_api_key)])
def recent_meetings(limit: int = 10, caller: dict = Depends(resolve_caller)):
    meetings = list_recent(
        limit=min(limit, 20),
        user_email=caller["email"],
        is_admin=caller["is_admin"],
    )
    return {
        "count": len(meetings),
        "viewer": caller["email"],
        "scope": "all" if caller["is_admin"] else "participant_only",
        "meetings": [_meeting_card(m) for m in meetings],
    }


@router.get("/meetings/search", dependencies=[Depends(verify_api_key)])
def search_meetings(q: str, limit: int = 5, caller: dict = Depends(resolve_caller)):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")
    meetings = search_by_title(
        q.strip(),
        limit=min(limit, 10),
        user_email=caller["email"],
        is_admin=caller["is_admin"],
    )
    return {
        "query": q,
        "count": len(meetings),
        "viewer": caller["email"],
        "scope": "all" if caller["is_admin"] else "participant_only",
        "meetings": [_meeting_card(m) for m in meetings],
    }


@router.get("/meetings/{meeting_id}/summary", dependencies=[Depends(verify_api_key)])
def get_meeting_summary(meeting_id: str, caller: dict = Depends(resolve_caller)):
    record = get_by_meeting_id(meeting_id)
    if not record or not user_can_access(record, caller["email"], is_admin=caller["is_admin"]):
        # Same response whether missing or forbidden — do not leak existence.
        raise HTTPException(status_code=404, detail="Meeting summary not found.")
    return {
        "meeting_id": record["meeting_id"],
        "meeting_title": record["meeting_title"],
        "summary": record["summary"],
        "created_at": record["created_at"],
        "created_at_local": record["created_at_local"],
        "attendee_count": len(record["attendee_emails"]),
        "viewer": caller["email"],
    }


@router.post("/meetings/{meeting_id}/resend", dependencies=[Depends(verify_api_key)])
def resend_meeting_summary(meeting_id: str, caller: dict = Depends(resolve_caller)):
    record = get_by_meeting_id(meeting_id)
    if not record or not user_can_access(record, caller["email"], is_admin=caller["is_admin"]):
        raise HTTPException(status_code=404, detail="Meeting summary not found.")
    if not record["attendee_emails"]:
        raise HTTPException(status_code=400, detail="No attendee emails stored for this meeting.")

    send_summary_email(
        record["attendee_emails"],
        record["meeting_title"],
        record["summary"],
    )
    return {
        "status": "sent",
        "meeting_id": meeting_id,
        "meeting_title": record["meeting_title"],
        "recipient_count": len(record["attendee_emails"]),
        "requested_by": caller["email"],
    }
