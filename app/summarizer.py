from openai import AzureOpenAI

from app.config import settings
from app.email_template import strip_code_fence

client = AzureOpenAI(
    api_key=settings.azure_openai_api_key,
    api_version=settings.azure_openai_api_version,
    azure_endpoint=settings.azure_openai_endpoint,
)


def summarize_transcript(meeting_title: str, transcript_text: str) -> str:
    trimmed = transcript_text[:120000]
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
    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": "You create concise enterprise meeting summaries."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    content = response.choices[0].message.content or ""
    return strip_code_fence(content) or "Summary unavailable."
