from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import settings
from app.db import get_by_meeting_id, list_recent, search_by_title
from app.mailer import send_summary_email

router = APIRouter()


def verify_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.copilot_api_key:
        raise HTTPException(status_code=503, detail="Copilot API key not configured.")
    if x_api_key != settings.copilot_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key.")


@router.get("/meetings/recent", dependencies=[Depends(verify_api_key)])
def recent_meetings(limit: int = 10):
    meetings = list_recent(limit=min(limit, 20))
    return {
        "count": len(meetings),
        "meetings": [
            {
                "meeting_id": m["meeting_id"],
                "meeting_title": m["meeting_title"],
                "created_at": m["created_at"],
            }
            for m in meetings
        ],
    }


@router.get("/meetings/search", dependencies=[Depends(verify_api_key)])
def search_meetings(q: str, limit: int = 5):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")
    meetings = search_by_title(q.strip(), limit=min(limit, 10))
    return {
        "query": q,
        "count": len(meetings),
        "meetings": [
            {
                "meeting_id": m["meeting_id"],
                "meeting_title": m["meeting_title"],
                "created_at": m["created_at"],
            }
            for m in meetings
        ],
    }


@router.get("/meetings/{meeting_id}/summary", dependencies=[Depends(verify_api_key)])
def get_meeting_summary(meeting_id: str):
    record = get_by_meeting_id(meeting_id)
    if not record:
        raise HTTPException(status_code=404, detail="Meeting summary not found.")
    return {
        "meeting_id": record["meeting_id"],
        "meeting_title": record["meeting_title"],
        "summary": record["summary"],
        "created_at": record["created_at"],
        "attendee_count": len(record["attendee_emails"]),
    }


@router.post("/meetings/{meeting_id}/resend", dependencies=[Depends(verify_api_key)])
def resend_meeting_summary(meeting_id: str):
    record = get_by_meeting_id(meeting_id)
    if not record:
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
    }
