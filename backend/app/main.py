"""GenStudio FastAPI backend."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import config, generations

app = FastAPI(title="GenStudio API", version="0.2.0")

# dev-friendly CORS; tighten for production origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generations.router)
app.include_router(config.router)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "env": s.app_env}
