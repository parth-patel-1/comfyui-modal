"""GenStudio FastAPI backend."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import db_mode, get_pool
from app.routers import admin, config, engines, generations, templates

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
app.include_router(engines.router)
app.include_router(config.router)
app.include_router(templates.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    out: dict = {"status": "ok", "env": s.app_env, "db_pool_mode": db_mode()}
    try:  # pool stats are admin-useful; never fail the probe over them
        st = get_pool().get_stats()
        out["db_pool"] = {
            "size": st.get("pool_size"),
            "available": st.get("pool_available"),
            "waiting": st.get("requests_waiting"),
            "usage_ms": st.get("usage_ms"),
        }
    except Exception:  # pragma: no cover - pool not initialized yet
        pass
    return out
