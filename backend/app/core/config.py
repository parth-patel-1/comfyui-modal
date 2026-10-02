"""Application settings loaded from environment / .env file.

The backend talks to Postgres through the Supabase connection pooler
(Supavisor) -- the worker queue uses FOR UPDATE SKIP LOCKED, which
PostgREST cannot express, and privileged writes are simpler over SQL
than REST. DB_POOL_MODE selects how:

  session     pooler port 5432; one server session per client for the
              lifetime of the connection (default, most compatible).
  transaction pooler port 6543; server sessions are shared between
              clients per-transaction. Scales to far more concurrent
              clients; requires prepared statements to be disabled
              (db.py sets psycopg prepare_threshold=None for you).
  direct      db.<ref>.supabase.co:5432, no pooler. Needed only for
              migrations / session-level features; requires IPv4
              connectivity to the database host.

SUPABASE_SERVICE_KEY is only required for Storage API operations
performed by the worker (uploading finished outputs).
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

    # Postgres via Supabase pooler (e.g. aws-0-<region>.pooler.supabase.com).
    # db_pool_mode: session | transaction | direct (see module docstring).
    db_url: str
    db_pool_mode: str = "session"
    db_pool_min_size: int = 1
    db_pool_max_size: int = 8

    # App
    app_env: str = "dev"
    log_level: str = "INFO"

    # Worker
    worker_poll_interval_s: float = 2.0
    job_timeout_s: int = 1200
    cold_start_wait_s: float = 900.0  # max time to wait for a cold Modal engine

    # ComfyUI engines (Modal URLs; also stored in modal_settings table)
    image_engine_url: str = ""
    video_engine_url: str = ""
    engine_bearer_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
