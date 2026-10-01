"""Inspect GenStudio DB state: grants, RLS, buckets, migrations.

Usage: python scripts/db_check.py
Requires DB_CONNECT_STRING or PGURL env var (pooler session URL).
"""

import os
import sys

import psycopg

TABLES = [
    "profiles", "app_settings", "modal_settings", "credit_wallets",
    "credit_transactions", "gpu_rates", "pricing_rules", "engine_configs",
    "generations", "generation_events", "admin_audit_log", "deploy_runs",
]


def main() -> None:
    url = os.environ.get("PGURL") or os.environ.get("DB_CONNECT_STRING")
    if not url:
        sys.exit("set PGURL or DB_CONNECT_STRING")

    with psycopg.connect(url) as conn, conn.cursor() as cur:
        print("== tables ==")
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' order by 1"
        )
        found = {r[0] for r in cur.fetchall()}
        for t in TABLES:
            print(f"  {'OK ' if t in found else 'MISSING'} {t}")

        print("== row counts (seed) ==")
        for t in ("gpu_rates", "pricing_rules", "engine_configs",
                  "app_settings", "modal_settings"):
            cur.execute(f"select count(*) from public.{t}")  # noqa: S608
            print(f"  {t}: {cur.fetchone()[0]}")

        print("== grants on public tables ==")
        cur.execute(
            "select table_name, grantee, privilege_type "
            "from information_schema.role_table_grants "
            "where table_schema = 'public' "
            "and grantee in ('anon', 'authenticated', 'service_role') "
            "order by table_name, grantee"
        )
        rows = cur.fetchall()
        if not rows:
            print("  (none found!)")
        by_table: dict[str, dict[str, set[str]]] = {}
        for table, grantee, priv in rows:
            by_table.setdefault(table, {}).setdefault(grantee, set()).add(priv)
        for t in TABLES:
            g = by_table.get(t, {})
            summary = "; ".join(
                f"{gr}: {','.join(sorted(ps))}" for gr, ps in sorted(g.items())
            )
            print(f"  {t}: {summary or 'NO GRANTS'}")

        print("== rls enabled ==")
        cur.execute(
            "select relname, relrowsecurity from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and relkind = 'r' order by 1"
        )
        for name, rls in cur.fetchall():
            print(f"  {name}: rls={rls}")

        print("== policies count per table ==")
        cur.execute(
            "select tablename, count(*) from pg_policies "
            "where schemaname = 'public' group by 1 order by 1"
        )
        for name, n in cur.fetchall():
            print(f"  {name}: {n}")

        print("== roles ==")
        cur.execute(
            "select rolname, rolbypassrls, rolsuper from pg_roles "
            "where rolname in ('anon', 'authenticated', 'service_role', 'postgres')"
        )
        for name, bypass, super_ in cur.fetchall():
            print(f"  {name}: bypassrls={bypass} super={super_}")

        print("== storage buckets ==")
        cur.execute("select id, public, file_size_limit from storage.buckets order by 1")
        for bid, pub, limit in cur.fetchall():
            print(f"  {bid}: public={pub} size_limit={limit}")

        print("== realtime publication ==")
        cur.execute(
            "select schemaname, tablename from pg_publication_tables "
            "where pubname = 'supabase_realtime' and schemaname = 'public'"
        )
        for schema, table in cur.fetchall():
            print(f"  {schema}.{table}")

        print("== applied migrations ==")
        cur.execute(
            "select version, name from supabase_migrations.schema_migrations "
            "order by version desc limit 5"
        )
        for version, name in cur.fetchall():
            print(f"  {version} {name}")

        print("== key functions ==")
        cur.execute(
            "select proname, prosecdef from pg_proc p "
            "join pg_namespace n on n.oid = pronamespace "
            "where n.nspname = 'public' order by 1"
        )
        for name, sdef in cur.fetchall():
            print(f"  {name}: security_definer={sdef}")


if __name__ == "__main__":
    main()
