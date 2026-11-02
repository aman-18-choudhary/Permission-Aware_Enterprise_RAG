from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"  # dev | prod
    secret_key: str = "change-me"
    database_url: str = "sqlite:///./dev.db"
    qdrant_url: str = ":memory:"  # http://localhost:6333 in docker
    qdrant_collection: str = "chunks"

    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768

    google_client_id: str = ""
    google_client_secret: str = ""
    # Public URL of the frontend. Next.js proxies /api/* to this backend, so
    # the OAuth redirect URI is {public_url}/api/auth/callback.
    public_url: str = "http://localhost:3000"
    admin_emails: str = ""  # comma separated
    auth_dev_mode: bool = False  # enables /auth/dev-login. NEVER in production.

    github_token: str = ""
    max_upload_mb: int = 10
    force_ipv4: bool = False  # set true if outbound calls hang (broken IPv6 route)

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    def validate_for_runtime(self) -> None:
        if self.env == "prod":
            if self.secret_key == "change-me" or len(self.secret_key) < 32:
                raise RuntimeError("SECRET_KEY must be set (32+ chars) in production")
            if self.auth_dev_mode:
                raise RuntimeError("AUTH_DEV_MODE must be off in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
