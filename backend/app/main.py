"""GenStudio FastAPI backend."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import admin, config, generations, templates

app = FastAPI(title="GenStudio API", version="0.3.0")

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
app.include_router(templates.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "env": s.app_env}
