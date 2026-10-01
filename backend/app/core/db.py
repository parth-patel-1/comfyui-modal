"""Direct Postgres access (session pooler) for API + SKIP LOCKED worker."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().db_url,
            min_size=1,
            max_size=8,
            open=True,
            kwargs={"autocommit": False},
        )
    return _pool


@contextmanager
def db_conn() -> Iterator[psycopg.Connection]:
    """Pooled connection with autocommit=False; commits on clean exit."""
    with get_pool().connection() as conn:
        yield conn
