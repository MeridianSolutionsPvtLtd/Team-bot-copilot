from openai import AzureOpenAI

from app.config import settings

client = AzureOpenAI(
    api_key=settings.azure_openai_api_key,
    api_version=settings.azure_openai_api_version,
    azure_endpoint=settings.azure_openai_endpoint,
)


def summarize_transcript(meeting_title: str, transcript_text: str) -> str:
    trimmed = transcript_text[:120000]
    prompt = f"""
You are a meeting analyst.
Return structured output in markdown with these sections:
1) Executive Summary (max 6 bullets)
2) Key Decisions
3) Action Items (owner, action, due date if available)
4) Risks/Blockers

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
    return response.choices[0].message.content or "Summary unavailable."
