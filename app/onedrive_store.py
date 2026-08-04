"""Per-user OneDrive meeting summary store via Microsoft Graph.

Each internal attendee gets the summary in their own OneDrive:

  /{ONEDRIVE_FOLDER}/summaries/{transcript_hash}.json
  /{ONEDRIVE_FOLDER}/index.json

Dedup markers live on the meeting organizer's drive:

  /{ONEDRIVE_FOLDER}/processed/{transcript_hash}.json

External guests (no mailbox/OneDrive in the tenant) are skipped for file
storage; they still receive the ACS email when an address is available.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.auth import get_access_token
from app.config import settings
from app.timeutils import now_utc_iso, to_local_string

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
INDEX_FILE = "index.json"


def _headers(content_type: str | None = "application/json") -> dict[str, str]:
    headers = {"Authorization": f"Bearer {get_access_token()}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _folder() -> str:
    folder = (settings.onedrive_folder or "MeetingIntelligence").strip().strip("/")
    return folder or "MeetingIntelligence"


def _drive_item_url(owner: str, path: str) -> str:
    encoded = quote(path.strip("/"), safe="/")
    return f"{GRAPH_BASE}/users/{quote(owner)}/drive/root:/{encoded}"


def _transcript_hash(transcript_id: str) -> str:
    return hashlib.sha256(transcript_id.encode("utf-8")).hexdigest()[:40]


def _summary_path(transcript_id: str) -> str:
    return f"{_folder()}/summaries/{_transcript_hash(transcript_id)}.json"


def _index_path() -> str:
    return f"{_folder()}/{INDEX_FILE}"


def _processed_path(transcript_id: str) -> str:
    return f"{_folder()}/processed/{_transcript_hash(transcript_id)}.json"


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    with httpx.Client(timeout=60) as client:
        return client.request(method, url, **kwargs)


def _ensure_folder(owner: str, path: str) -> None:
    parts = [p for p in path.strip("/").split("/") if p]
    current = ""
    for part in parts:
        current = f"{current}/{part}" if current else part
        probe = _request("GET", _drive_item_url(owner, current), headers=_headers())
        if probe.status_code == 200:
            continue
        parent = "/".join(current.split("/")[:-1])
        if parent:
            create_url = f"{_drive_item_url(owner, parent)}:/children"
        else:
            create_url = f"{GRAPH_BASE}/users/{quote(owner)}/drive/root/children"
        payload = {
            "name": part,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        }
        created = _request("POST", create_url, headers=_headers(), json=payload)
        if created.status_code in {200, 201, 409}:
            continue
        logger.error(
            "Failed to create OneDrive folder '%s' for %s (%s): %s",
            current,
            owner,
            created.status_code,
            created.text,
        )
        created.raise_for_status()


def _put_json(owner: str, path: str, payload: dict[str, Any]) -> None:
    url = f"{_drive_item_url(owner, path)}:/content"
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    response = _request("PUT", url, headers=_headers("application/json"), content=body)
    if response.is_error:
        logger.error(
            "OneDrive PUT %s for %s failed (%s): %s",
            path,
            owner,
            response.status_code,
            response.text,
        )
        response.raise_for_status()


def _get_json(owner: str, path: str) -> dict[str, Any] | None:
    url = f"{_drive_item_url(owner, path)}:/content"
    response = _request("GET", url, headers=_headers(None))
    if response.status_code == 404:
        return None
    if response.is_error:
        logger.error(
            "OneDrive GET %s for %s failed (%s): %s",
            path,
            owner,
            response.status_code,
            response.text,
        )
        response.raise_for_status()
    return response.json()


def _user_has_drive(owner: str) -> bool:
    """True when Graph can open this user's OneDrive (internal tenant user)."""
    drive = _request(
        "GET",
        f"{GRAPH_BASE}/users/{quote(owner)}/drive?$select=id",
        headers=_headers(),
    )
    if drive.status_code == 200:
        return True
    logger.info(
        "No OneDrive for %s (%s): %s",
        owner,
        drive.status_code,
        (drive.text or "")[:200],
    )
    return False


def _to_record(item: dict) -> dict:
    created_at = item.get("created_at", "")
    return {
        "transcript_id": item.get("transcript_id", ""),
        "meeting_id": item.get("meeting_id", ""),
        "meeting_title": item.get("meeting_title") or "Microsoft Teams Meeting",
        "attendee_emails": item.get("attendee_emails") or [],
        "summary": item.get("summary") or "",
        "created_at": created_at,
        "created_at_local": item.get("created_at_local") or to_local_string(created_at),
    }


def _load_index(owner: str) -> list[dict]:
    data = _get_json(owner, _index_path())
    if not data:
        return []
    items = data.get("items") or []
    return items if isinstance(items, list) else []


def _save_index(owner: str, items: list[dict]) -> None:
    items = sorted(items, key=lambda row: row.get("created_at", ""), reverse=True)
    _put_json(owner, _index_path(), {"items": items})


def _write_summary_for_user(owner: str, document: dict) -> bool:
    try:
        if not _user_has_drive(owner):
            logger.info("Skipping OneDrive write for %s (no tenant mailbox/drive).", owner)
            return False
        _ensure_folder(owner, f"{_folder()}/summaries")
        _put_json(owner, _summary_path(document["transcript_id"]), document)
        index = _load_index(owner)
        index = [row for row in index if row.get("transcript_id") != document["transcript_id"]]
        index.append(
            {
                "transcript_id": document["transcript_id"],
                "meeting_id": document["meeting_id"],
                "meeting_title": document["meeting_title"],
                "attendee_emails": document["attendee_emails"],
                "created_at": document["created_at"],
                "created_at_local": document["created_at_local"],
            }
        )
        _save_index(owner, index)
        return True
    except Exception:
        logger.exception("Failed writing summary to OneDrive for %s", owner)
        return False


def init_db() -> None:
    # Folders are created per user on first write — nothing org-wide to init.
    logger.info(
        "OneDrive per-user storage active (folder=/%s). "
        "Each attendee receives summaries in their own drive.",
        _folder(),
    )


def is_processed(transcript_id: str, organizer_user_id: str | None = None) -> bool:
    """Dedup check on the organizer's drive (or optional fallback owner)."""
    owner = (organizer_user_id or settings.onedrive_owner_upn or "").strip()
    if not owner:
        logger.warning("is_processed called without organizer_user_id; treating as not processed.")
        return False
    try:
        return _get_json(owner, _processed_path(transcript_id)) is not None
    except Exception:
        logger.exception("Could not read processed marker for %s", transcript_id)
        return False


def mark_processed(
    transcript_id: str,
    meeting_id: str,
    summary: str,
    meeting_title: str = "",
    attendee_emails: list[str] | None = None,
    organizer_user_id: str | None = None,
) -> None:
    created_at = now_utc_iso()
    emails = sorted(
        {
            e.strip().lower()
            for e in (attendee_emails or [])
            if isinstance(e, str) and "@" in e
        }
    )
    document = {
        "transcript_id": transcript_id,
        "meeting_id": meeting_id,
        "meeting_title": meeting_title,
        "attendee_emails": emails,
        "summary": summary,
        "created_at": created_at,
        "created_at_local": to_local_string(created_at),
    }

    # Dedup marker on organizer drive so webhook retries do not re-run.
    organizer = (organizer_user_id or settings.onedrive_owner_upn or "").strip()
    if organizer:
        try:
            _ensure_folder(organizer, f"{_folder()}/processed")
            _put_json(
                organizer,
                _processed_path(transcript_id),
                {
                    "transcript_id": transcript_id,
                    "meeting_id": meeting_id,
                    "created_at": created_at,
                },
            )
        except Exception:
            logger.exception("Failed to write processed marker on organizer drive %s", organizer)

    # Personal copy for every internal attendee (and organizer if email known).
    targets = list(emails)
    written = 0
    for owner in targets:
        if _write_summary_for_user(owner, document):
            written += 1

    logger.info(
        "Stored meeting summary on %d OneDrive(s) for transcript %s",
        written,
        transcript_id,
    )


def get_by_meeting_id(meeting_id: str, user_email: str | None = None) -> dict | None:
    owner = (user_email or "").strip().lower()
    if not owner:
        return None
    matches = [row for row in _load_index(owner) if row.get("meeting_id") == meeting_id]
    if not matches:
        return None
    matches.sort(key=lambda row: row.get("created_at", ""), reverse=True)
    latest = matches[0]
    full = _get_json(owner, _summary_path(latest["transcript_id"]))
    return _to_record(full or latest)


def user_can_access(record: dict, user_email: str, *, is_admin: bool = False) -> bool:
    # With per-user OneDrive, presence in the caller's drive is the primary gate.
    # Keep attendee check as defense-in-depth for resend/summary APIs.
    if is_admin:
        return True
    email = (user_email or "").strip().lower()
    if not email:
        return False
    return email in {e.strip().lower() for e in (record.get("attendee_emails") or [])}


def list_recent(limit: int = 10, user_email: str | None = None, *, is_admin: bool = False) -> list[dict]:
    # Always read the signed-in user's own OneDrive — no org-wide store.
    del is_admin  # unused in per-user mode; kept for API compatibility
    owner = (user_email or "").strip().lower()
    if not owner:
        return []
    items = sorted(_load_index(owner), key=lambda row: row.get("created_at", ""), reverse=True)[:limit]
    return [_to_record(row) for row in items]


def search_by_title(
    query: str,
    limit: int = 5,
    user_email: str | None = None,
    *,
    is_admin: bool = False,
) -> list[dict]:
    del is_admin
    owner = (user_email or "").strip().lower()
    if not owner:
        return []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    items = [row for row in _load_index(owner) if pattern.search(row.get("meeting_title") or "")]
    items = sorted(items, key=lambda row: row.get("created_at", ""), reverse=True)[:limit]
    return [_to_record(row) for row in items]
