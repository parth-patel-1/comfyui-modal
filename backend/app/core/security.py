"""JWT verification against the Supabase Auth server.

Verifies a user's access token by calling {url}/auth/v1/user with the
token; a 200 means the JWT is valid and active. Results are cached
briefly to keep the hot path cheap.
"""

from __future__ import annotations

import time

import httpx

from app.core.config import get_settings

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_S = 60.0


class AuthError(Exception):
    pass


def verify_token(token: str) -> dict:
    """Return the auth user dict for a valid access token; raise AuthError."""
    now = time.monotonic()
    cached = _CACHE.get(token)
    if cached and cached[0] > now:
        return cached[1]

    s = get_settings()
    try:
        resp = httpx.get(
            f"{s.supabase_url}/auth/v1/user",
            headers={"apikey": s.supabase_anon_key, "Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        raise AuthError(f"auth server unreachable: {e}") from e

    if resp.status_code != 200:
        raise AuthError("invalid or expired token")

    user = resp.json()
    _CACHE[token] = (now + _CACHE_TTL_S, user)
    return user
