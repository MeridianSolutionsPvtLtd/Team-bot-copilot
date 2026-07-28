import logging
import re
from datetime import datetime, timezone
from functools import lru_cache

from pymongo import MongoClient
from pymongo.errors import OperationFailure

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_collection():
    if not settings.cosmos_connection_string:
        raise RuntimeError("Cosmos DB is not configured. Set COSMOS_CONNECTION_STRING.")
    client = MongoClient(settings.cosmos_connection_string)
    database = client[settings.cosmos_database]
    return database[settings.cosmos_container]


def _ensure_index(collection, keys, **kwargs) -> None:
    try:
        collection.create_index(keys, **kwargs)
    except OperationFailure as exc:
        # Cosmos DB for MongoDB may reject index changes on existing collections.
        logger.warning("Skipping index creation for %s: %s", keys, exc.details or str(exc))


def init_db() -> None:
    collection = _get_collection()
    # Non-unique indexes only; Cosmos MongoDB restricts unique index changes on existing collections.
    _ensure_index(collection, "transcript_id")
    _ensure_index(collection, "meeting_id")
    _ensure_index(collection, [("created_at", -1)])


def _to_record(item: dict) -> dict:
    return {
        "transcript_id": item.get("transcript_id", ""),
        "meeting_id": item.get("meeting_id", ""),
        "meeting_title": item.get("meeting_title") or "Microsoft Teams Meeting",
        "attendee_emails": item.get("attendee_emails") or [],
        "summary": item.get("summary") or "",
        "created_at": item.get("created_at", ""),
    }


def is_processed(transcript_id: str) -> bool:
    return _get_collection().find_one({"transcript_id": transcript_id}, {"_id": 1}) is not None


def mark_processed(
    transcript_id: str,
    meeting_id: str,
    summary: str,
    meeting_title: str = "",
    attendee_emails: list[str] | None = None,
) -> None:
    document = {
        "transcript_id": transcript_id,
        "meeting_id": meeting_id,
        "meeting_title": meeting_title,
        "attendee_emails": attendee_emails or [],
        "summary": summary,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _get_collection().update_one(
        {"transcript_id": transcript_id},
        {"$set": document},
        upsert=True,
    )


def get_by_meeting_id(meeting_id: str) -> dict | None:
    item = _get_collection().find_one(
        {"meeting_id": meeting_id},
        sort=[("created_at", -1)],
    )
    return _to_record(item) if item else None


def list_recent(limit: int = 10) -> list[dict]:
    items = _get_collection().find().sort("created_at", -1).limit(limit)
    return [_to_record(item) for item in items]


def search_by_title(query: str, limit: int = 5) -> list[dict]:
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    items = (
        _get_collection()
        .find({"meeting_title": pattern})
        .sort("created_at", -1)
        .limit(limit)
    )
    return [_to_record(item) for item in items]
