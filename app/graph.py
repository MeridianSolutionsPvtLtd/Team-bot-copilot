import logging
from typing import Any

import httpx

from app.auth import get_access_token
from app.config import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TARGET_RESOURCE = "communications/onlineMeetings/getAllTranscripts"


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    base = {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
    }
    if extra:
        base.update(extra)
    return base


def _request(method: str, url: str, **kwargs) -> Any:
    with httpx.Client(timeout=30) as client:
        response = client.request(method, url, headers=_headers(kwargs.pop("headers", None)), **kwargs)
    if response.is_error:
        error_body = response.text
        logger.error("Graph API %s %s failed (%s): %s", method, url, response.status_code, error_body)
        response.raise_for_status()
    if response.text:
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text
    return None


def list_subscriptions() -> list[dict]:
    data = _request("GET", f"{GRAPH_BASE}/subscriptions")
    return data.get("value", [])


def _subscription_expiry() -> str:
    from datetime import datetime, timedelta, timezone

    expiry = datetime.now(timezone.utc) + timedelta(days=2)
    return expiry.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def create_subscription() -> dict:
    payload = {
        "changeType": "created",
        "notificationUrl": settings.webhook_public_url,
        "resource": TARGET_RESOURCE,
        "expirationDateTime": _subscription_expiry(),
        "clientState": settings.client_state,
    }
    lifecycle_url = settings.lifecycle_notification_url or settings.webhook_public_url
    payload["lifecycleNotificationUrl"] = lifecycle_url
    logger.info("Creating Graph subscription for resource: %s", TARGET_RESOURCE)
    return _request("POST", f"{GRAPH_BASE}/subscriptions", json=payload)


def renew_subscription(subscription_id: str) -> dict:
    payload = {"expirationDateTime": _subscription_expiry()}
    lifecycle_url = settings.lifecycle_notification_url or settings.webhook_public_url
    payload["lifecycleNotificationUrl"] = lifecycle_url
    logger.info("Renewing Graph subscription: %s", subscription_id)
    return _request("PATCH", f"{GRAPH_BASE}/subscriptions/{subscription_id}", json=payload)


def get_meeting_details(meeting_id: str, user_id: str | None = None) -> dict:
    if user_id:
        return _request("GET", f"{GRAPH_BASE}/users/{user_id}/onlineMeetings/{meeting_id}")
    return _request("GET", f"{GRAPH_BASE}/communications/onlineMeetings/{meeting_id}")


def get_attendance_records(meeting_id: str, user_id: str | None = None) -> list[dict]:
    """Attendance records list everyone who actually joined, including external guests."""
    base = (
        f"{GRAPH_BASE}/users/{user_id}/onlineMeetings/{meeting_id}"
        if user_id
        else f"{GRAPH_BASE}/communications/onlineMeetings/{meeting_id}"
    )
    try:
        data = _request("GET", f"{base}/attendanceReports?$expand=attendanceRecords")
    except Exception as exc:
        logger.warning("Could not read attendance reports for meeting %s: %s", meeting_id, exc)
        return []

    records: list[dict] = []
    for report in (data or {}).get("value", []):
        records.extend(report.get("attendanceRecords") or [])
    return records


def get_transcript_content(meeting_id: str, transcript_id: str, user_id: str | None = None) -> str:
    headers = {"Accept": "text/vtt"}
    if user_id:
        return _request(
            "GET",
            f"{GRAPH_BASE}/users/{user_id}/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content",
            headers=headers,
        )
    return _request(
        "GET",
        f"{GRAPH_BASE}/communications/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content",
        headers=headers,
    )
