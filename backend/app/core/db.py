"""Direct Postgres access for the SKIP LOCKED worker loop.

The queue claim requires `FOR UPDATE SKIP LOCKED`, which is not exposed
through PostgREST, so the worker uses psycopg directly.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

_pool: ConnectionPool | None = None


def _url() -> str:
    s = get_settings()
    if s.db_url:
        return s.db_url
    raise RuntimeError(
        "DB_URL not configured: add DB_CONNECT_STRING-style pooler URL to .env as DB_URL"
    )


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            _url(),
            min_size=1,
            max_size=8,
            open=True,
            kwargs={"autocommit": False},
        )
    return _pool


@contextmanager
def db_conn() -> Iterator[psycopg.Connection]:
    pool = get_pool()
    with pool.connection() as conn:
        yield conn
