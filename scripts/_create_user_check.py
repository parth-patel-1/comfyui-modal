"""Validate POST /api/admin/users (manual user creation). Cleans up after itself."""
import json
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = "http://localhost:8900"

env = {}
for line in (ROOT / "backend" / ".env").read_text().splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

creds = json.loads((ROOT / "scripts" / ".testuser").read_text())

def supa(path: str, body: dict | None, key: str, method="POST"):
    req = urllib.request.Request(
        f"{env['SUPABASE_URL']}/auth/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"apikey": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

tok = supa("token?grant_type=password",
           {"email": creds["email"], "password": creds["password"]},
           env["SUPABASE_ANON_KEY"])["access_token"]

def api(path: str, body=None, method="POST"):
    req = urllib.request.Request(
        f"{BACKEND}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)

email = f"manual_{secrets.token_hex(4)}@genstudio.dev"
password = "ManualTest!" + secrets.token_hex(4)
fail = []

# 1. create user
st, out = api("/api/admin/users", {
    "email": email, "password": password,
    "display_name": "Manual Check", "role": "user", "grant_credits": 5,
})
uid = out.get("id") if isinstance(out, dict) else None
print(f"create: {st} {json.dumps(out)[:200]}")
if st != 200 or not uid:
    fail.append("create failed"); print("FAIL"); raise SystemExit(1)

# 2. duplicate -> 400
st2, out2 = api("/api/admin/users", {"email": email, "password": password})
print(f"duplicate: {st2} {json.dumps(out2)[:120]}")
if st2 != 400:
    fail.append(f"duplicate expected 400 got {st2}")

# 3. invalid payload -> 422
st3, out3 = api("/api/admin/users", {"email": "not-an-email", "password": "x" * 8})
print(f"invalid: {st3}")
if st3 != 422:
    fail.append(f"invalid expected 422 got {st3}")

# 4. the user can actually log in
try:
    login = supa("token?grant_type=password",
                 {"email": email, "password": password},
                 env["SUPABASE_ANON_KEY"])
    ok_login = bool(login.get("access_token"))
except Exception:
    ok_login = False
print(f"login as new user: {'OK' if ok_login else 'FAILED'}")
if not ok_login:
    fail.append("new user cannot log in")

# 5. shows up in admin list with role + balance (signup grant + 5)
st5, users = api(f"/api/admin/users?q={email}", method="GET")
row = next((u for u in users if u["email"] == email), None)
print(f"list: {st5} found={row is not None} "
      f"role={row and row['role']} balance={row and row['balance']}")
if row is None or row["role"] != "user" or (row["balance"] or 0) < 5:
    fail.append("list row missing/role/balance wrong")

# 6. audit entry recorded
st6, audit = api("/api/admin/audit?limit=10", method="GET")
has_audit = any(a["action"] == "user.create" and a["target"] == uid for a in audit)
print(f"audit user.create: {'OK' if has_audit else 'MISSING'}")
if not has_audit:
    fail.append("audit entry missing")

# cleanup: delete auth user (cascades to profile/wallet) via direct SQL
import psycopg
try:
    with psycopg.connect(env["DB_URL"]) as dconn, dconn.cursor() as cur:
        cur.execute("delete from auth.users where id = %s", (uid,))
    print("cleanup: deleted test user")
except Exception as e:  # noqa: BLE001
    print(f"cleanup: FAILED ({e}) — user {uid} remains")

if fail:
    print("FAIL:", "; ".join(fail))
    raise SystemExit(1)
print("PASS: manual user creation end-to-end")
