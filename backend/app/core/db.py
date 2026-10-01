"""Postgres access via the Supabase pooler (Supavisor) for API + SKIP LOCKED worker.

DB_POOL_MODE controls where the psycopg ConnectionPool connects:

  session     pooler :5432 -- a server session is pinned to each pooled
              connection for its lifetime. Most compatible; the pool
              still caps how many server sessions the app holds.
  transaction pooler :6543 -- server sessions are handed back to the
              Supavisor pool after every transaction, so a huge number
              of app clients can share a small server connection pool.
              Prepared statements do NOT survive transaction pooling:
              psycopg's default prepare_threshold=5 (and 0, which means
              "prepare on first use", NOT "off") raises
              DuplicatePreparedStatement under load. We therefore set
              prepare_threshold=None (never prepare) -- verified against
              the live pooler, including the FOR UPDATE SKIP LOCKED
              worker claim.
  direct      db.<ref>.supabase.co:5432 -- no pooler; derived from the
              pooler URL's postgres.<ref> username. For migrations and
              session-level features only.

All app queries run in short single-transaction blocks (db_conn), so
they are safe under every mode.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import conninfo
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

logger = logging.getLogger("app.db")

_pool: ConnectionPool | None = None

_POOLER_SUFFIX = ".pooler.supabase.com"
_MODE_PORTS = {"session": 5432, "transaction": 6543}


def db_mode() -> str:
    """Normalized pool mode: 'session' | 'transaction' | 'direct'."""
    mode = get_settings().db_pool_mode.strip().lower()
    if mode not in ("session", "transaction", "direct"):
        logger.warning("unknown DB_POOL_MODE %r; falling back to 'session'", mode)
        return "session"
    return mode


def _conninfo() -> dict:
    """DB_URL rewritten for the active pool mode."""
    parts = conninfo.conninfo_to_dict(get_settings().db_url)
    host = str(parts.get("host", ""))
    if db_mode() == "direct":
        if host.endswith(_POOLER_SUFFIX):
            # postgres.<project-ref> -> db.<project-ref>.supabase.co
            ref = str(parts.get("user", "")).removeprefix("postgres.").split(".")[0]
            if ref:
                parts["host"] = f"db.{ref}.supabase.co"
                parts["user"] = "postgres"
            else:
                logger.warning("DB_POOL_MODE=direct but cannot derive project ref "
                               "from user %r; keeping pooler host", parts.get("user"))
        parts["port"] = 5432
    elif host.endswith(_POOLER_SUFFIX):
        parts["port"] = _MODE_PORTS[db_mode()]
    else:
        # non-pooler host (already direct); leave host/port untouched
        logger.info("DB_URL host %s is not a pooler host; using it as-is", host)
    parts.setdefault("sslmode", "require")
    return parts


def _configure(conn: psycopg.Connection) -> None:
    """Per-connection tuning (called by the pool on every new connection)."""
    if db_mode() == "transaction":
        # Prepared statements break under transaction pooling (server
        # sessions are shared after COMMIT). None = never prepare.
        conn.prepare_threshold = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = ConnectionPool(
            conninfo=conninfo.make_conninfo(**_conninfo()),
            name=f"genstudio-db[{db_mode()}]",
            min_size=max(0, s.db_pool_min_size),
            max_size=max(s.db_pool_min_size, s.db_pool_max_size),
            max_lifetime=1800,  # recycle before pooler idle eviction
            check=ConnectionPool.check_connection,
            configure=_configure,
            open=True,
            kwargs={"autocommit": False},
        )
        logger.info("db pool open: mode=%s host=%s port=%s size=%s-%s",
                    db_mode(), _conninfo().get("host"), _conninfo().get("port"),
                    s.db_pool_min_size, s.db_pool_max_size)
    return _pool


@contextmanager
def db_conn() -> Iterator[psycopg.Connection]:
    """Pooled connection with autocommit=False; commits on clean exit."""
    with get_pool().connection() as conn:
        yield conn
