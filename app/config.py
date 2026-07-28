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

    mail_from: str
    sqlite_path: str = "./meeting_agent.db"
    copilot_api_key: str = ""

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
