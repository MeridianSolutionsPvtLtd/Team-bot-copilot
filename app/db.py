import json
import sqlite3
from contextlib import contextmanager

from app.config import settings


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _cursor():
    conn = _connect()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_transcripts (
                transcript_id TEXT PRIMARY KEY,
                meeting_id TEXT NOT NULL,
                meeting_title TEXT,
                attendee_emails TEXT,
                summary TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_meeting_id ON processed_transcripts(meeting_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_meeting_title ON processed_transcripts(meeting_title)"
        )


def is_processed(transcript_id: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            "SELECT 1 FROM processed_transcripts WHERE transcript_id = ? LIMIT 1",
            (transcript_id,),
        )
        return cur.fetchone() is not None


def mark_processed(
    transcript_id: str,
    meeting_id: str,
    summary: str,
    meeting_title: str = "",
    attendee_emails: list[str] | None = None,
) -> None:
    emails_json = json.dumps(attendee_emails or [])
    with _cursor() as cur:
        cur.execute(
            """
            INSERT OR REPLACE INTO processed_transcripts
            (transcript_id, meeting_id, meeting_title, attendee_emails, summary)
            VALUES (?, ?, ?, ?, ?)
            """,
            (transcript_id, meeting_id, meeting_title, emails_json, summary),
        )


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "transcript_id": row["transcript_id"],
        "meeting_id": row["meeting_id"],
        "meeting_title": row["meeting_title"] or "Microsoft Teams Meeting",
        "attendee_emails": json.loads(row["attendee_emails"] or "[]"),
        "summary": row["summary"] or "",
        "created_at": row["created_at"],
    }


def get_by_meeting_id(meeting_id: str) -> dict | None:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT * FROM processed_transcripts
            WHERE meeting_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (meeting_id,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def list_recent(limit: int = 10) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT * FROM processed_transcripts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_row_to_dict(row) for row in cur.fetchall()]


def search_by_title(query: str, limit: int = 5) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT * FROM processed_transcripts
            WHERE meeting_title LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (f"%{query}%", limit),
        )
        return [_row_to_dict(row) for row in cur.fetchall()]
