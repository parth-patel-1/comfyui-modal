"""Supabase client factories.

Two clients:
- service_client(): privileged (service/secret key) for backend writes.
- user_client(token): acts as the caller; RLS applies.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.core.config import get_settings


@lru_cache
def service_client() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_key)


def user_client(token: str) -> Client:
    """Client bound to a caller's JWT; respects RLS policies."""
    s = get_settings()
    client = create_client(s.supabase_url, s.supabase_key)
    client.postgrest.auth(token)
    return client
