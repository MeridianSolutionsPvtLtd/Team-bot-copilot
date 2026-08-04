import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParsedResource:
    transcript_id: str
    meeting_id: str
    user_id: str | None = None


USER_SCOPED_PATTERN = re.compile(
    r"users\('([^']+)'\)/onlineMeetings\('([^']+)'\)/transcripts\('([^']+)'\)",
    re.IGNORECASE,
)

ALL_TRANSCRIPTS_PATTERN = re.compile(
    r"getAllTranscripts\('([^']+)'\)/transcripts\('([^']+)'\)",
    re.IGNORECASE,
)


def parse_graph_resource(resource: str) -> ParsedResource | None:
    if not resource:
        logger.warning("parse_graph_resource: empty resource string.")
        return None

    user_match = USER_SCOPED_PATTERN.search(resource)
    if user_match:
        parsed = ParsedResource(
            user_id=user_match.group(1),
            meeting_id=user_match.group(2),
            transcript_id=user_match.group(3),
        )
        logger.info(
            "Parsed user-scoped resource user_id=%s meeting_id=%s transcript_id=%s",
            parsed.user_id,
            parsed.meeting_id,
            parsed.transcript_id,
        )
        return parsed

    all_match = ALL_TRANSCRIPTS_PATTERN.search(resource)
    if all_match:
        # For getAllTranscripts notifications, Graph provides a meeting key-like identifier.
        parsed = ParsedResource(
            user_id=None,
            meeting_id=all_match.group(1),
            transcript_id=all_match.group(2),
        )
        logger.info(
            "Parsed getAllTranscripts resource meeting_id=%s transcript_id=%s (no user_id in path)",
            parsed.meeting_id,
            parsed.transcript_id,
        )
        return parsed

    logger.warning("parse_graph_resource: unrecognized resource format: %s", resource[:300])
    return None
