from typing import Any

import httpx

from app.auth import get_access_token
from app.config import settings

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


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
    response.raise_for_status()
    if response.text:
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text
    return None


def list_subscriptions() -> list[dict]:
    data = _request("GET", f"{GRAPH_BASE}/subscriptions")
    return data.get("value", [])


def create_subscription() -> dict:
    payload = {
        "changeType": "created",
        "notificationUrl": settings.webhook_public_url,
        "resource": "communications/onlineMeetings/getAllTranscripts",
        "expirationDateTime": _subscription_expiry(),
        "clientState": settings.client_state,
    }
    if settings.lifecycle_notification_url:
        payload["lifecycleNotificationUrl"] = settings.lifecycle_notification_url
    return _request("POST", f"{GRAPH_BASE}/subscriptions", json=payload)


def renew_subscription(subscription_id: str) -> dict:
    payload = {"expirationDateTime": _subscription_expiry()}
    if settings.lifecycle_notification_url:
        payload["lifecycleNotificationUrl"] = settings.lifecycle_notification_url
    return _request("PATCH", f"{GRAPH_BASE}/subscriptions/{subscription_id}", json=payload)


def _subscription_expiry() -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


def get_meeting_details(meeting_id: str, user_id: str | None = None) -> dict:
    if user_id:
        return _request("GET", f"{GRAPH_BASE}/users/{user_id}/onlineMeetings/{meeting_id}")
    return _request("GET", f"{GRAPH_BASE}/communications/onlineMeetings/{meeting_id}")


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
