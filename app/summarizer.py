from __future__ import annotations

import logging

from openai import AzureOpenAI

from app.config import settings
from app.email_template import strip_code_fence

logger = logging.getLogger(__name__)

client = AzureOpenAI(
    api_key=settings.azure_openai_api_key,
    api_version=settings.azure_openai_api_version,
    azure_endpoint=settings.azure_openai_endpoint,
)


def summarize_transcript(meeting_title: str, transcript_text: str) -> str:
    trimmed = transcript_text[:120000]
    logger.info(
        "Summarizing meeting '%s' with Azure OpenAI deployment=%s transcript_chars=%d truncated=%s",
        meeting_title,
        settings.azure_openai_deployment,
        len(transcript_text),
        len(transcript_text) > len(trimmed),
    )
    prompt = f"""
You are a meeting analyst.
Return structured markdown with these sections, each as a level-2 heading:
## Executive Summary (max 6 bullets)
## Key Decisions
## Action Items (a markdown table with columns: Owner | Action | Due Date)
## Risks/Blockers

Rules:
- Do not wrap the response in code fences.
- Do not repeat the meeting title as a heading.
- Skip a section entirely if the transcript has nothing for it.

Meeting Title: {meeting_title}
Transcript:
{trimmed}
"""
    try:
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": "You create concise enterprise meeting summaries."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
    except Exception:
        logger.exception("Azure OpenAI summarization failed for '%s'.", meeting_title)
        raise

    content = response.choices[0].message.content or ""
    summary = strip_code_fence(content) or "Summary unavailable."
    logger.info(
        "Summary generated for '%s' summary_chars=%d",
        meeting_title,
        len(summary),
    )
    return summary
