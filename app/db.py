"""Meeting summary persistence.

Active backend: OneDrive (via Microsoft Graph) — see app/onedrive_store.py
Cosmos DB code is kept below, fully commented, for easy rollback.
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ACTIVE: OneDrive storage
# ---------------------------------------------------------------------------
if (settings.storage_backend or "onedrive").strip().lower() != "cosmos":
    from app.onedrive_store import (  # noqa: F401
        get_by_meeting_id,
        init_db,
        is_processed,
        list_recent,
        mark_email_sent,
        mark_processed,
        marker_email_already_sent,
        release_processing_claim,
        search_by_title,
        try_claim_processing,
        user_can_access,
    )
else:
    # Optional rollback path: set STORAGE_BACKEND=cosmos and uncomment Cosmos block
    # below, then remove/disable this raise.
    raise RuntimeError(
        "STORAGE_BACKEND=cosmos is set, but Cosmos code is commented out in app/db.py. "
        "Uncomment the Cosmos section to re-enable it, or set STORAGE_BACKEND=onedrive."
    )


# ---------------------------------------------------------------------------
# COMMENTED OUT: Cosmos DB (MongoDB API) — previous storage backend
# Uncomment this block and set STORAGE_BACKEND=cosmos to roll back.
# ---------------------------------------------------------------------------
#
# import re
# from functools import lru_cache
#
# from pymongo import MongoClient
# from pymongo.errors import OperationFailure
#
# from app.timeutils import now_utc_iso, to_local_string
#
#
# @lru_cache(maxsize=1)
# def _get_collection():
#     if not settings.cosmos_connection_string:
#         raise RuntimeError("Cosmos DB is not configured. Set COSMOS_CONNECTION_STRING.")
#     client = MongoClient(settings.cosmos_connection_string)
#     database = client[settings.cosmos_database]
#     return database[settings.cosmos_container]
#
#
# def _ensure_index(collection, keys, **kwargs) -> None:
#     try:
#         collection.create_index(keys, **kwargs)
#     except OperationFailure as exc:
#         # Cosmos DB for MongoDB may reject index changes on existing collections.
#         logger.warning("Skipping index creation for %s: %s", keys, exc.details or str(exc))
#
#
# def init_db() -> None:
#     collection = _get_collection()
#     # Non-unique indexes only; Cosmos MongoDB restricts unique index changes on existing collections.
#     _ensure_index(collection, "transcript_id")
#     _ensure_index(collection, "meeting_id")
#     _ensure_index(collection, "attendee_emails")
#     _ensure_index(collection, [("created_at", -1)])
#
#
# def _to_record(item: dict) -> dict:
#     created_at = item.get("created_at", "")
#     return {
#         "transcript_id": item.get("transcript_id", ""),
#         "meeting_id": item.get("meeting_id", ""),
#         "meeting_title": item.get("meeting_title") or "Microsoft Teams Meeting",
#         "attendee_emails": item.get("attendee_emails") or [],
#         "summary": item.get("summary") or "",
#         "created_at": created_at,
#         "created_at_local": item.get("created_at_local") or to_local_string(created_at),
#     }
#
#
# def is_processed(transcript_id: str) -> bool:
#     return _get_collection().find_one({"transcript_id": transcript_id}, {"_id": 1}) is not None
#
#
# def mark_processed(
#     transcript_id: str,
#     meeting_id: str,
#     summary: str,
#     meeting_title: str = "",
#     attendee_emails: list[str] | None = None,
# ) -> None:
#     # created_at stays UTC so sorting is consistent; the local field is for display only.
#     created_at = now_utc_iso()
#     document = {
#         "transcript_id": transcript_id,
#         "meeting_id": meeting_id,
#         "meeting_title": meeting_title,
#         "attendee_emails": attendee_emails or [],
#         "summary": summary,
#         "created_at": created_at,
#         "created_at_local": to_local_string(created_at),
#     }
#     _get_collection().update_one(
#         {"transcript_id": transcript_id},
#         {"$set": document},
#         upsert=True,
#     )
#
#
# def get_by_meeting_id(meeting_id: str) -> dict | None:
#     item = _get_collection().find_one(
#         {"meeting_id": meeting_id},
#         sort=[("created_at", -1)],
#     )
#     return _to_record(item) if item else None
#
#
# def user_can_access(record: dict, user_email: str, *, is_admin: bool = False) -> bool:
#     if is_admin:
#         return True
#     email = (user_email or "").strip().lower()
#     if not email:
#         return False
#     return email in {e.strip().lower() for e in (record.get("attendee_emails") or [])}
#
#
# def list_recent(limit: int = 10, user_email: str | None = None, *, is_admin: bool = False) -> list[dict]:
#     query: dict = {}
#     if user_email and not is_admin:
#         query["attendee_emails"] = user_email.strip().lower()
#     items = _get_collection().find(query).sort("created_at", -1).limit(limit)
#     return [_to_record(item) for item in items]
#
#
# def search_by_title(
#     query: str,
#     limit: int = 5,
#     user_email: str | None = None,
#     *,
#     is_admin: bool = False,
# ) -> list[dict]:
#     pattern = re.compile(re.escape(query), re.IGNORECASE)
#     filters: dict = {"meeting_title": pattern}
#     if user_email and not is_admin:
#         filters["attendee_emails"] = user_email.strip().lower()
#     items = (
#         _get_collection()
#         .find(filters)
#         .sort("created_at", -1)
#         .limit(limit)
#     )
#     return [_to_record(item) for item in items]
