import re
from dataclasses import dataclass


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
        return None

    user_match = USER_SCOPED_PATTERN.search(resource)
    if user_match:
        return ParsedResource(
            user_id=user_match.group(1),
            meeting_id=user_match.group(2),
            transcript_id=user_match.group(3),
        )

    all_match = ALL_TRANSCRIPTS_PATTERN.search(resource)
    if all_match:
        # For getAllTranscripts notifications, Graph provides a meeting key-like identifier.
        return ParsedResource(
            user_id=None,
            meeting_id=all_match.group(1),
            transcript_id=all_match.group(2),
        )

    return None
