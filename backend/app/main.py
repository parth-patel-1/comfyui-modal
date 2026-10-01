"""GenStudio FastAPI backend entrypoint (Phase 0 shell)."""

from fastapi import FastAPI

from app.core.config import get_settings

app = FastAPI(title="GenStudio API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "env": s.app_env}
