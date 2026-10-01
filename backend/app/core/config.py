"""Application settings loaded from environment / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """GenStudio backend configuration.

    All values come from environment variables (optionally a .env file).
    SUPABASE_KEY must be the secret/service key (sb_secret_... or legacy
    service_role JWT) because the backend performs privileged writes.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_key: str  # service/secret key for backend-side privileged access

    # Optional direct Postgres URL (session pooler) for the SKIP LOCKED
    # worker loop; falls back to deriving from supabase project ref.
    db_url: str | None = None

    # App
    app_env: str = "dev"
    log_level: str = "INFO"

    # Worker
    worker_poll_interval_s: float = 1.0
    worker_batch_size: int = 4
    job_timeout_s: int = 900

    # ComfyUI (Modal endpoints, set after Phase 1 deploy)
    image_engine_url: str = ""
    video_engine_url: str = ""
    engine_bearer_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
