"""Temporary probe: psycopg3 behaviour against the Supabase TRANSACTION pooler (6543).

Determines: (1) whether default prepare_threshold breaks under transaction
pooling, (2) which value disables prepared statements, (3) whether the
FOR UPDATE SKIP LOCKED worker claim pattern works in transaction mode.
"""
import os
import sys

import psycopg
from psycopg import conninfo

base = os.environ.get("DB_URL") or sys.argv[1]
p = conninfo.conninfo_to_dict(base)
host, user = p["host"], p["user"]
password, dbname = p.get("password", ""), p.get("dbname", "postgres")
print(f"base host={host} user={user}")

tx = (f"host={host} port=6543 user={user} password={password} "
      f"dbname={dbname} sslmode=require")


def run(url: str, threshold, label: str, times: int = 8) -> bool:
    try:
        with psycopg.connect(url, connect_timeout=15) as conn:
            conn.prepare_threshold = threshold
            for _ in range(times):
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("select count(*) from public.profiles")
                        cur.fetchone()
        print(f"{label}: OK ({times} repeated queries across transactions)")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"{label}: FAILED -> {type(e).__name__}: {str(e)[:140]}")
        return False


with psycopg.connect(base, connect_timeout=15) as c:
    default_threshold = c.prepare_threshold
print(f"psycopg default prepare_threshold = {default_threshold!r}")

# baseline: session pooler (5432) with psycopg defaults
run(base, default_threshold, "[session 5432, default]")

# transaction pooler with psycopg default (N executions -> PREPARE)
ok = run(tx, default_threshold, f"[tx 6543, default threshold={default_threshold}]")
print(f"--> transaction pooler breaks with defaults: {not ok}")

# candidate fixes
run(tx, 0, "[tx 6543, prepare_threshold=0]")
run(tx, None, "[tx 6543, prepare_threshold=None]")

# worker claim pattern (FOR UPDATE SKIP LOCKED) inside a transaction,
# with prepare_threshold=None (the safe value)
claim_sql = ("select id, status from public.generations "
             "where status = 'queued' order by created_at for update skip locked limit 1")
try:
    with psycopg.connect(tx, connect_timeout=15) as conn:
        conn.prepare_threshold = None
        for i in range(3):
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(claim_sql)
                    print(f"[skip locked pass {i}] rows={len(cur.fetchall())}")
    print("[skip locked, threshold=None]: OK")
except Exception as e:  # noqa: BLE001
    print(f"[skip locked, threshold=None]: FAILED -> {type(e).__name__}: {str(e)[:140]}")
