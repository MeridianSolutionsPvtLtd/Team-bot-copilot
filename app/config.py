from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    tenant_id: str
    client_id: str
    client_secret: str
    client_state: str

    webhook_public_url: str
    lifecycle_notification_url: str | None = None

    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    azure_openai_api_version: str = "2024-02-15-preview"

    acs_connection_string: str
    acs_email_from: str

    # --- Storage: OneDrive is active; Cosmos kept for easy rollback ---
    # Active backend: "onedrive" (default) or "cosmos"
    storage_backend: str = "onedrive"

    # OneDrive (Graph) — each attendee gets summaries in their own drive.
    # ONEDRIVE_OWNER_UPN is optional fallback only for processed-marker if organizer id is missing.
    onedrive_owner_upn: str = ""
    onedrive_folder: str = "MeetingIntelligence"

    # Cosmos DB for MongoDB (commented-out path in app/db.py; kept for rollback)
    cosmos_connection_string: str = ""
    cosmos_database: str = "meeting-intelligence"
    cosmos_container: str = "transcripts"

    copilot_api_key: str = ""
    # Comma-separated emails that may view any meeting summary (optional).
    copilot_admin_emails: str = ""

    display_timezone: str = "Asia/Kolkata"

    def admin_email_set(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.copilot_admin_emails.split(",")
            if email.strip() and "@" in email
        }

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
