"""Per-user OneDrive meeting summary store via Microsoft Graph.

Each internal attendee gets the summary in their own OneDrive:

  /{ONEDRIVE_FOLDER}/summaries/{transcript_hash}.json
  /{ONEDRIVE_FOLDER}/index.json

Dedup markers live on the meeting organizer's drive:

  /{ONEDRIVE_FOLDER}/processed/{transcript_hash}.json

Marker lifecycle: claim processing → write attendee summaries → mark done →
send email → set email_sent. Reads fail closed; stale processing locks expire
after PROCESSING_LOCK_TTL.

External guests (no mailbox/OneDrive in the tenant) are skipped for file
storage; they still receive the ACS email when an address is available.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.auth import get_access_token
from app.config import settings
from app.timeutils import now_utc_iso, to_local_string

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
INDEX_FILE = "index.json"

# Stale "processing" markers can be reclaimed after a crash / killed worker.
PROCESSING_LOCK_TTL = timedelta(minutes=30)
MARKER_STATUS_PROCESSING = "processing"
MARKER_STATUS_DONE = "done"


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
    response = _request(
        "PUT",
        url,
        headers=_headers("application/json"),
        content=body,
    )
    if response.is_error:
        logger.error(
            "OneDrive PUT %s for %s failed (%s): %s",
            path,
            owner,
            response.status_code,
            response.text,
        )
        response.raise_for_status()
    logger.info(
        "OneDrive PUT OK path=%s owner=%s status=%s bytes=%d",
        path,
        owner,
        response.status_code,
        len(body),
    )


def _get_json(owner: str, path: str) -> dict[str, Any] | None:
    """Download a JSON file from OneDrive. Empty / non-JSON bodies return None."""
    url = f"{_drive_item_url(owner, path)}:/content"
    # Prefer the raw file bytes; avoid forcing a JSON Accept that some Graph
    # edges answer with an empty body right after an upload.
    headers = _headers(None)
    headers["Accept"] = "*/*"
    response = _request("GET", url, headers=headers)
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

    raw = (response.content or b"").strip()
    if not raw:
        logger.warning(
            "OneDrive GET returned empty body path=%s owner=%s status=%s content_type=%s",
            path,
            owner,
            response.status_code,
            response.headers.get("content-type"),
        )
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "OneDrive GET non-JSON body path=%s owner=%s status=%s preview=%r err=%s",
            path,
            owner,
            response.status_code,
            raw[:120],
            exc,
        )
        return None
    if not isinstance(data, dict):
        logger.warning(
            "OneDrive GET JSON was not an object path=%s owner=%s type=%s",
            path,
            owner,
            type(data).__name__,
        )
        return None
    return data


def _get_json_with_retry(
    owner: str,
    path: str,
    *,
    attempts: int = 4,
    delay_seconds: float = 0.75,
) -> dict[str, Any] | None:
    """OneDrive content can be briefly empty right after PUT — retry a few times."""
    last: dict[str, Any] | None = None
    for attempt in range(1, attempts + 1):
        last = _get_json(owner, path)
        if last is not None:
            return last
        if attempt < attempts:
            time.sleep(delay_seconds)
    return last


def _delete_path(owner: str, path: str) -> None:
    response = _request("DELETE", _drive_item_url(owner, path), headers=_headers(None))
    if response.status_code in {204, 404}:
        return
    if response.is_error:
        logger.error(
            "OneDrive DELETE %s for %s failed (%s): %s",
            path,
            owner,
            response.status_code,
            response.text,
        )
        response.raise_for_status()


def _marker_owner(organizer_user_id: str | None) -> str:
    return (organizer_user_id or settings.onedrive_owner_upn or "").strip()


def _parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _marker_is_stale(marker: dict[str, Any]) -> bool:
    updated = _parse_iso(marker.get("updated_at") or marker.get("created_at"))
    if updated is None:
        return True
    return datetime.now(timezone.utc) - updated > PROCESSING_LOCK_TTL


def _is_fully_complete(marker: dict[str, Any] | None) -> bool:
    """True when this transcript should never be processed again."""
    if not marker:
        return False
    status = (marker.get("status") or "").strip().lower()
    # Legacy markers had no status and were written only after email + store.
    if not status:
        return True
    if status == MARKER_STATUS_DONE:
        return bool(marker.get("email_sent"))
    return False


def _marker_blocks_processing(marker: dict[str, Any] | None) -> bool:
    """True when another worker owns the transcript or work is fully finished."""
    if not marker:
        return False
    if _is_fully_complete(marker):
        return True
    status = (marker.get("status") or "").strip().lower()
    # done but email not sent yet — allow reclaim to finish email.
    if status == MARKER_STATUS_DONE:
        return False
    if status == MARKER_STATUS_PROCESSING:
        return not _marker_is_stale(marker)
    return True


def _read_marker(owner: str, transcript_id: str) -> dict[str, Any] | None:
    return _get_json(owner, _processed_path(transcript_id))


def _read_marker_after_write(owner: str, transcript_id: str) -> dict[str, Any] | None:
    return _get_json_with_retry(owner, _processed_path(transcript_id))


def _write_marker(owner: str, transcript_id: str, payload: dict[str, Any]) -> None:
    _ensure_folder(owner, f"{_folder()}/processed")
    _put_json(owner, _processed_path(transcript_id), payload)


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


def _write_summary_for_user(owner: str, document: dict) -> str:
    """Return 'written', 'skipped' (no drive), or 'failed'."""
    try:
        if not _user_has_drive(owner):
            logger.info("Skipping OneDrive write for %s (no tenant mailbox/drive).", owner)
            return "skipped"
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
        return "written"
    except Exception:
        logger.exception("Failed writing summary to OneDrive for %s", owner)
        return "failed"


def init_db() -> None:
    # Folders are created per user on first write — nothing org-wide to init.
    logger.info(
        "OneDrive per-user storage active (folder=/%s). "
        "Each attendee receives summaries in their own drive.",
        _folder(),
    )


def is_processed(transcript_id: str, organizer_user_id: str | None = None) -> bool:
    """Fail-closed dedup gate for webhook intake.

    Returns True (skip work) when:
    - organizer/fallback owner is missing
    - Graph marker read fails
    - marker is fully complete (done + email_sent, or legacy marker)
    - marker is processing and not stale
    """
    owner = _marker_owner(organizer_user_id)
    if not owner:
        logger.warning(
            "is_processed called without organizer_user_id; fail-closed (skip processing)."
        )
        return True
    try:
        marker = _read_marker(owner, transcript_id)
    except Exception:
        logger.exception(
            "Could not read processed marker for %s; fail-closed (skip processing).",
            transcript_id,
        )
        return True
    return _marker_blocks_processing(marker)


def try_claim_processing(
    transcript_id: str,
    meeting_id: str,
    organizer_user_id: str | None = None,
) -> str | None:
    """Claim the processing lock. Returns claim_id on success, else None."""
    owner = _marker_owner(organizer_user_id)
    if not owner:
        logger.warning(
            "Cannot claim processing for %s: missing organizer_user_id.",
            transcript_id,
        )
        return None

    try:
        existing = _read_marker(owner, transcript_id)
        if _marker_blocks_processing(existing):
            logger.info(
                "Transcript %s already claimed/done on %s (status=%s).",
                transcript_id,
                owner,
                (existing or {}).get("status"),
            )
            return None

        claim_id = str(uuid.uuid4())
        now = now_utc_iso()
        payload = {
            "transcript_id": transcript_id,
            "meeting_id": meeting_id,
            "status": MARKER_STATUS_PROCESSING,
            "email_sent": bool((existing or {}).get("email_sent")),
            "claim_id": claim_id,
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        if existing:
            for key in ("meeting_title", "summary", "attendee_emails", "written_owners"):
                if key in existing:
                    payload[key] = existing[key]

        _write_marker(owner, transcript_id, payload)

        # Verify we won any concurrent claim race. OneDrive may return an empty
        # body for a moment after PUT, so retry before giving up.
        confirmed = _read_marker_after_write(owner, transcript_id)
        if confirmed is None:
            logger.warning(
                "Claim write succeeded for %s but re-read is still empty; "
                "accepting in-memory claim_id=%s",
                transcript_id,
                claim_id,
            )
            return claim_id
        if confirmed.get("claim_id") != claim_id:
            logger.info(
                "Lost processing claim race for transcript %s (theirs=%s ours=%s).",
                transcript_id,
                confirmed.get("claim_id"),
                claim_id,
            )
            return None
        logger.info("Processing claim confirmed for transcript %s claim_id=%s", transcript_id, claim_id)
        return claim_id
    except Exception:
        logger.exception("Failed to claim processing lock for %s", transcript_id)
        return None


def release_processing_claim(
    transcript_id: str,
    claim_id: str,
    organizer_user_id: str | None = None,
) -> None:
    """Delete a processing marker we still own so webhook retries can resume."""
    owner = _marker_owner(organizer_user_id)
    if not owner or not claim_id:
        return
    try:
        marker = _read_marker(owner, transcript_id)
        if not marker:
            return
        if marker.get("claim_id") != claim_id:
            return
        if (marker.get("status") or "").strip().lower() != MARKER_STATUS_PROCESSING:
            return
        _delete_path(owner, _processed_path(transcript_id))
        logger.info("Released processing claim for transcript %s.", transcript_id)
    except Exception:
        logger.exception("Failed releasing processing claim for %s", transcript_id)


def marker_email_already_sent(
    transcript_id: str,
    organizer_user_id: str | None = None,
) -> bool:
    owner = _marker_owner(organizer_user_id)
    if not owner:
        return False
    try:
        marker = _read_marker(owner, transcript_id) or {}
        return bool(marker.get("email_sent"))
    except Exception:
        logger.exception("Could not read email_sent for %s", transcript_id)
        # Fail closed for email: avoid duplicates when marker state is unknown.
        return True


def mark_email_sent(
    transcript_id: str,
    claim_id: str,
    organizer_user_id: str | None = None,
) -> None:
    owner = _marker_owner(organizer_user_id)
    if not owner:
        raise RuntimeError("Cannot mark email_sent without organizer_user_id.")
    marker = _read_marker(owner, transcript_id) or {}
    if marker.get("claim_id") != claim_id:
        raise RuntimeError(f"Claim mismatch marking email_sent for {transcript_id}.")
    marker["email_sent"] = True
    marker["updated_at"] = now_utc_iso()
    _write_marker(owner, transcript_id, marker)


def mark_processed(
    transcript_id: str,
    meeting_id: str,
    summary: str,
    meeting_title: str = "",
    attendee_emails: list[str] | None = None,
    organizer_user_id: str | None = None,
    claim_id: str | None = None,
) -> bool:
    """Write attendee summaries first, then mark done.

    Returns True when the done marker was written successfully.
    Returns False on hard summary-write failures (done marker not written).
    """
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

    written = 0
    skipped = 0
    failed = 0
    written_owners: list[str] = []
    for owner in emails:
        result = _write_summary_for_user(owner, document)
        if result == "written":
            written += 1
            written_owners.append(owner)
        elif result == "skipped":
            skipped += 1
        else:
            failed += 1

    logger.info(
        "Stored meeting summary for transcript %s: written=%d skipped=%d failed=%d",
        transcript_id,
        written,
        skipped,
        failed,
    )

    if failed:
        logger.error(
            "Aborting done marker for %s due to %d OneDrive write failure(s).",
            transcript_id,
            failed,
        )
        return False

    organizer = _marker_owner(organizer_user_id)
    if not organizer:
        logger.error("Cannot write done marker for %s: missing organizer.", transcript_id)
        return False

    existing = _read_marker(organizer, transcript_id) or {}
    if claim_id and existing.get("claim_id") not in {None, claim_id}:
        logger.error("Claim mismatch writing done marker for %s.", transcript_id)
        return False

    marker = {
        "transcript_id": transcript_id,
        "meeting_id": meeting_id,
        "meeting_title": meeting_title,
        "attendee_emails": emails,
        "summary": summary,
        "written_owners": written_owners,
        "status": MARKER_STATUS_DONE,
        # No recipients ⇒ nothing to email; treat as already handled.
        "email_sent": bool(existing.get("email_sent")) or not emails,
        "claim_id": claim_id or existing.get("claim_id"),
        "created_at": existing.get("created_at") or created_at,
        "updated_at": created_at,
    }
    _write_marker(organizer, transcript_id, marker)
    return True


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
