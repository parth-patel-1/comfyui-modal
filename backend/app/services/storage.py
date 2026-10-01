"""Supabase Storage operations.

Two auth modes:
1. SUPABASE_SERVICE_KEY (secret key) -- used directly if configured.
2. Worker service account: signs in with WORKER_EMAIL/WORKER_PASSWORD and
   uses its JWT; Storage RLS policies allow role='service' profiles to
   read references and write outputs.
"""

from __future__ import annotations

import time

import httpx

from app.core.config import get_settings


class StorageError(RuntimeError):
    pass


_token_cache: tuple[float, str] | None = None  # (expiry, jwt)


def _service_headers() -> dict[str, str]:
    s = get_settings()
    if s.supabase_service_key:
        return {"apikey": s.supabase_service_key,
                "Authorization": f"Bearer {s.supabase_service_key}"}
    return {"apikey": s.supabase_anon_key,
            "Authorization": f"Bearer {_worker_jwt()}"}


def _worker_jwt() -> str:
    """Password grant for the worker service account (cached until expiry)."""
    global _token_cache
    now = time.monotonic()
    if _token_cache and _token_cache[0] > now + 60:
        return _token_cache[1]

    s = get_settings()
    if not s.worker_email or not s.worker_password:
        raise StorageError(
            "no storage auth: set SUPABASE_SERVICE_KEY or "
            "WORKER_EMAIL/WORKER_PASSWORD in backend/.env"
        )
    resp = httpx.post(
        f"{s.supabase_url}/auth/v1/token?grant_type=password",
        json={"email": s.worker_email, "password": s.worker_password},
        headers={"apikey": s.supabase_anon_key},
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise StorageError(f"worker sign-in failed: {resp.status_code}")
    payload = resp.json()
    jwt = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    _token_cache = (now + expires_in, jwt)
    return jwt


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=get_settings().supabase_url,
        headers=_service_headers(),
        timeout=httpx.Timeout(60.0, read=600.0),
    )


def download(bucket: str, path: str) -> bytes:
    with _client() as client:
        resp = client.get(f"/storage/v1/object/{bucket}/{path}")
    if resp.status_code != 200:
        raise StorageError(f"download {bucket}/{path}: {resp.status_code}")
    return resp.content


def upload(bucket: str, path: str, data: bytes, content_type: str = "image/png") -> None:
    with _client() as client:
        resp = client.post(
            f"/storage/v1/object/{bucket}/{path}",
            content=data,
            headers={"content-type": content_type, "x-upsert": "true"},
        )
    if resp.status_code not in (200, 201):
        raise StorageError(f"upload {bucket}/{path}: {resp.status_code} {resp.text[:200]}")
