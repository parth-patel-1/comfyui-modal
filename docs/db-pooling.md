# Database connection pooling (Supabase / Supavisor)

GenStudio does **not** connect to Postgres directly. It goes through the
Supabase connection pooler (**Supavisor**), which lets the platform serve a
large user base from a small number of real database connections.

## The three connection modes

| | Direct | Session pooler | Transaction pooler |
|---|---|---|---|
| Host / port | `db.<ref>.supabase.co:5432` | `aws-0-<region>.pooler.supabase.com:5432` | `aws-0-<region>.pooler.supabase.com:6543` |
| Server session per client | 1:1 (raw Postgres) | 1:1 while connected | **Shared, per-transaction** |
| Max concurrent clients | Postgres `max_connections` (~100) | Pooler client limit (thousands), but each pins a server session | Pooler client limit (thousands) sharing a small server pool |
| IPv4 reachable | IPv6 only (or paid IPv4 add-on) | ✅ | ✅ |

### Session pooler (port 5432) — previous default

**Pros**
- Full Postgres feature set: prepared statements, `SET`, temp tables,
  advisory locks, `LISTEN/NOTIFY`, cursors `WITH HOLD`.
- No code changes vs a direct connection.

**Cons**
- Every pooled connection **pins** a real server session until it closes,
  so scaling the app means scaling server connections too.
- Idle sessions still count against `max_connections`.

### Transaction pooler (port 6543) — **current setting**

**Pros**
- Server sessions are returned to Supavisor's pool after every
  transaction, so thousands of clients share a small server pool —
  this is what keeps the database from being overwhelmed as the user
  base grows.
- Compatible with every query this app runs (see "Verified" below).
- Same IPv4-friendly host as session mode — only the port changes.

**Cons / limitations (all handled or not applicable here)**
- **Prepared statements break.** psycopg3 auto-prepares a statement after
  5 executions (`prepare_threshold=5`), and **`prepare_threshold=0` does
  NOT disable preparing — it prepares on first use**. Both crash with
  `DuplicatePreparedStatement: "_pg3_0" already exists` once the pooler
  hands the session to another client. `db.py` therefore sets
  `prepare_threshold=None` (never prepare) on every pooled connection.
- Session-level state (`SET`, session advisory locks, `LISTEN/NOTIFY`,
  temp tables, `WITH HOLD` cursors) does not survive across
  transactions. GenStudio uses none of these — every request runs in one
  short `with db_conn() as conn` block.
- Slightly higher per-query latency (~1–2 ms pooler hop) and no
  prepared-statement speedup (negligible for our query mix).

### Direct connection

**Pros** — no pooler in the path; everything works.
**Cons** — needs IPv6 (or paid IPv4 add-on); each client is a real
server connection; one leaky client can exhaust `max_connections`.

## How it is configured

```env
DB_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
DB_POOL_MODE=transaction    # session | transaction | direct
DB_POOL_MIN_SIZE=1
DB_POOL_MAX_SIZE=8
```

`backend/app/core/db.py` rewrites the URL for the mode (transaction mode
is the same host on port **6543**; `direct` derives
`db.<ref>.supabase.co` from the `postgres.<ref>` username), forces
`sslmode=require`, and applies the psycopg compatibility fix
automatically. Verify at any time:

```
GET /health  ->  {"db_pool_mode": "transaction", "db_pool": {...}}
```

## Verified against the live project (2026-10-01)

`scripts/_pooler_probe.py` (delete after use) connected to the real
transaction pooler and confirmed:

| Test | Result |
|---|---|
| Session pooler :5432, psycopg defaults | ✅ OK |
| Transaction pooler :6543, `prepare_threshold=5` (default) | ❌ `DuplicatePreparedStatement` |
| Transaction pooler :6543, `prepare_threshold=0` | ❌ `DuplicatePreparedStatement` |
| Transaction pooler :6543, `prepare_threshold=None` | ✅ OK (8 repeated queries across transactions) |
| Worker claim (`FOR UPDATE SKIP LOCKED` + RPCs) @ :6543, threshold=None | ✅ OK |

## What admins / maintainers must know

- **Migrations and one-off scripts** (`supabase/migrations/*`, `scripts/db_check.py`,
  `scripts/setup_users.py`, …) read `DB_URL` directly and stay on the
  **session pooler :5432** — that is correct. Session-level tools (psql
  `\d`, `pg_dump`, DDL sessions) should keep using 5432 or the direct host.
- The FastAPI app and the worker (`app/worker/loop.py`) share
  `db_conn()`, so both run through the configured mode.
- If you ever add `SET`/advisory locks/`LISTEN` to app code, run them
  **inside the same transaction** that needs them, or switch
  `DB_POOL_MODE=session` first.
- Under heavy load, tune `DB_POOL_MAX_SIZE` (default 8) — with
  transaction mode this stays tiny while client throughput scales;
  Supavisor itself defaults to a 15-connection server pool per user.
- To roll back: set `DB_POOL_MODE=session` and restart the backend.
