import logging
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def display_tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.display_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown DISPLAY_TIMEZONE '%s'; falling back to UTC.", settings.display_timezone)
        return ZoneInfo("UTC")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_local_string(utc_iso: str) -> str:
    """Render a stored UTC timestamp in the configured display timezone."""
    if not utc_iso:
        return ""
    try:
        moment = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    except ValueError:
        return utc_iso
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(display_tz()).strftime("%d %b %Y, %I:%M %p %Z")


def now_local_string() -> str:
    return to_local_string(now_utc_iso())
