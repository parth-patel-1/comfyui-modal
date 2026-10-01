"""Create the worker service account + a test user, end to end.

- signs up via Supabase Auth (anon key)
- confirms emails and assigns roles via direct SQL (pooler, role postgres)
- seeds the test user's wallet with credits + ledger row
- appends WORKER_EMAIL/WORKER_PASSWORD to backend/.env

Usage: python scripts/setup_users.py
"""

import json
import secrets
import sys
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).parent.parent
ENV_PATH = ROOT / "backend" / ".env"


def load_env() -> dict[str, str]:
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def main() -> None:
    env = load_env()
    url, anon, db_url = env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"], env["DB_URL"]

    worker_email = "worker@genstudio.dev"
    worker_pw = secrets.token_urlsafe(18)
    test_email = "tester@genstudio.dev"
    test_pw = secrets.token_urlsafe(18)

    def signup(email: str, password: str, db) -> None:
        r = httpx.post(
            f"{url}/auth/v1/signup",
            json={"email": email, "password": password},
            headers={"apikey": anon},
            timeout=30,
        )
        data = r.json()
        if r.status_code in (200, 201) and data.get("id"):
            print(f"signed up {email}")
            return
        if "already" in str(data.get("msg", "")) or \
                data.get("error_code") == "user_already_exists":
            print(f"{email} already exists")
            return
        if r.status_code == 429:
            # email rate limit -- create the row directly (bcrypt via pgcrypto)
            with db.cursor() as cur:
                cur.execute(
                    "select id from auth.users where email = %s", (email,))
                if cur.fetchone():
                    print(f"{email} already exists")
                    return
                cur.execute(
                    "insert into auth.users "
                    "(id, instance_id, aud, role, email, encrypted_password, "
                    " email_confirmed_at, raw_app_meta_data, created_at, updated_at) "
                    "values (gen_random_uuid(), "
                    "'00000000-0000-0000-0000-000000000000', 'authenticated', "
                    "'authenticated', %s, crypt(%s, gen_salt('bf')), now(), "
                    "'{\"provider\":\"email\",\"providers\":[\"email\"]}', now(), now())",
                    (email, password),
                )
            print(f"created {email} via SQL (rate limited)")
            return
        sys.exit(f"signup failed for {email}: {r.status_code} {r.text[:300]}")

    with psycopg.connect(db_url) as conn:
        signup(worker_email, worker_pw, conn)
        signup(test_email, test_pw, conn)
        conn.commit()

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("select id from auth.users where email = %s", (worker_email,))
        worker_id = cur.fetchone()
        cur.execute("select id from auth.users where email = %s", (test_email,))
        test_id = cur.fetchone()
        if not worker_id or not test_id:
            sys.exit("users not found in auth.users after signup")
        worker_id, test_id = worker_id[0], test_id[0]

        # confirm emails + set roles
        cur.execute(
            "update auth.users set email_confirmed_at = now(), "
            "updated_at = now() where id in (%s, %s)",
            (worker_id, test_id),
        )
        cur.execute("update public.profiles set role = 'service' where id = %s",
                    (worker_id,))
        cur.execute("update public.profiles set role = 'user' where id = %s",
                    (test_id,))

        # GoTrue needs an auth.identities row and non-NULL token fields;
        # SQL-created users lack both, so align them with real signups.
        for uid, email in ((worker_id, worker_email), (test_id, test_email)):
            cur.execute("select count(*) from auth.identities where user_id = %s",
                        (uid,))
            if cur.fetchone()[0] == 0:
                cur.execute(
                    "insert into auth.identities "
                    "(id, user_id, provider, provider_id, identity_data, "
                    " last_sign_in_at, created_at, updated_at) "
                    "values (gen_random_uuid(), %s, 'email', %s, "
                    "jsonb_build_object('sub', %s::text, 'email', %s::text, "
                    "'email_verified', true), now(), now(), now())",
                    (uid, str(uid), str(uid), email),
                )
            cur.execute(
                "update auth.users set "
                " confirmation_token = '', recovery_token = '', "
                " email_change_token_new = '', email_change = '', "
                " raw_user_meta_data = jsonb_build_object("
                "   'sub', id::text, 'email', email, 'email_verified', true), "
                " is_sso_user = coalesce(is_sso_user, false) "
                "where id = %s",
                (uid,),
            )
        # keep the stored worker password in sync with backend/.env
        cur.execute(
            "update auth.users set encrypted_password = crypt(%s, gen_salt('bf')) "
            "where id = %s",
            (worker_pw, worker_id),
        )

        # seed test wallet: 20 credits with ledger row
        cur.execute(
            "insert into public.credit_wallets (user_id, balance) values (%s, 20) "
            "on conflict (user_id) do update set balance = 20",
            (test_id,),
        )
        cur.execute(
            "insert into public.credit_transactions "
            "(user_id, delta, balance_after, kind, note) "
            "values (%s, 20, 20, 'admin_grant', 'dev test seed')",
            (test_id,),
        )
        conn.commit()
        print(f"worker_id={worker_id}")
        print(f"test_id={test_id}")

    # persist worker creds for the backend
    lines = ENV_PATH.read_text().rstrip("\n").splitlines()
    pairs = {"WORKER_EMAIL": worker_email, "WORKER_PASSWORD": worker_pw}
    lines = [l for l in lines if l.split("=")[0] not in pairs]
    lines += [f"{k}={v}" for k, v in pairs.items()]
    ENV_PATH.write_text("\n".join(lines) + "\n")
    print("backend/.env updated with worker credentials")

    # stash test creds for the e2e script (gitignored)
    (ROOT / "scripts" / ".testuser").write_text(
        json.dumps({"email": test_email, "password": test_pw, "id": str(test_id)})
    )
    print("scripts/.testuser written")


if __name__ == "__main__":
    main()
