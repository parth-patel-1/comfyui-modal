"""Application settings loaded from environment / .env file.

The backend talks to Postgres DIRECTLY (session pooler) -- the worker
queue uses FOR UPDATE SKIP LOCKED, which PostgREST cannot express, and
privileged writes are simpler over SQL than REST. SUPABASE_SERVICE_KEY
is only required for Storage API operations performed by the worker
(uploading finished outputs).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_anon_key: str  # publishable key; used to verify user JWTs
    supabase_service_key: str = ""  # secret key; optional storage auth
    worker_email: str = ""  # service account (role='service') for storage
    worker_password: str = ""

    # Direct Postgres (session pooler, e.g. aws-0-<region>.pooler.supabase.com:5432)
    db_url: str

    # App
    app_env: str = "dev"
    log_level: str = "INFO"

    # Worker
    worker_poll_interval_s: float = 2.0
    job_timeout_s: int = 1200

    # ComfyUI engines (Modal URLs; also stored in modal_settings table)
    image_engine_url: str = ""
    video_engine_url: str = ""
    engine_bearer_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
