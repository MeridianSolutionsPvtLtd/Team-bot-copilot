# Python Meeting Intelligence Backend

Automatic Teams transcript processing backend using:
- Microsoft Graph webhook subscriptions
- Azure OpenAI summarization
- Azure Communication Services email delivery
- Azure Cosmos DB for MongoDB storage and deduplication
- FastAPI + APScheduler

## 1) Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill all values in `.env`.

## 2) Run locally

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Endpoints:
- `GET /health`
- `POST /graph/webhook`

## 3) Production notes

- Webhook URL must be public HTTPS and match `WEBHOOK_PUBLIC_URL`
- Configure Graph app permissions:
  - `OnlineMeetingTranscript.Read.All`
  - `OnlineMeetings.Read.All`
- Grant admin consent and Teams Application Access Policy
- Configure Azure Communication Services with a verified email domain
- Configure Azure Cosmos DB for MongoDB (serverless supported). Set `COSMOS_CONNECTION_STRING` in app settings.
- Keep service always on (App Service/Container App/VM)

## 4) Copilot Studio

Use Copilot Studio as conversational front-end; this backend stays event-driven and automatic.

**Full setup guide:** [docs/CopilotStudio.md](docs/CopilotStudio.md)

Copilot calls these APIs (header: `X-API-Key`):

| Endpoint | Purpose |
|----------|---------|
| `GET /api/meetings/recent` | List recent summarized meetings |
| `GET /api/meetings/search?q=` | Search by meeting title |
| `GET /api/meetings/{id}/summary` | Get full summary |
| `POST /api/meetings/{id}/resend` | Resend summary email to attendees |
