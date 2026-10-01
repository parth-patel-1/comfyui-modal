"""Regression: the admin Users page can create a user via the '+ New user' form.

Logs in as the admin test user, opens the create-user form, submits it,
verifies the new row appears in the table, then deletes the test user.

Run:  python scripts/_admin_create_user_ui.py   (frontend + backend running)
Artifacts: _pw_shots/admin_create_user_ui.png
"""
import json
import secrets
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = "http://localhost:3000"
SB_URL = "https://egimurphizmxkckabslx.supabase.co"
SB_KEY = "sb_publishable_5CVRJZYxbJwqp1UgWq8vyg_TPLnzioK"
STORAGE_KEY = "sb-egimurphizmxkckabslx-auth-token"
SHOT = ROOT / "_pw_shots" / "admin_create_user_ui.png"

creds = json.loads((ROOT / "scripts" / ".testuser").read_text())

req = urllib.request.Request(
    f"{SB_URL}/auth/v1/token?grant_type=password",
    data=json.dumps({"email": creds["email"], "password": creds["password"]}).encode(),
    headers={"apikey": SB_KEY, "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=20) as r:
    session = json.load(r)

suffix = secrets.token_hex(3)
email = f"manual_ui_{suffix}@genstudio.dev"
password = "UiCheck!" + secrets.token_hex(4)
fail: list[str] = []

env = dict(
    l.split("=", 1) for l in (ROOT / "backend" / ".env").read_text().splitlines() if "=" in l
)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(
        f"window.localStorage.setItem({STORAGE_KEY!r}, {json.dumps(session)!r});"
    )
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(f"{FRONTEND}/admin/users", wait_until="load", timeout=20000)
    page.wait_for_selector("table", timeout=15000)

    page.get_by_role("button", name="+ New user").click()
    page.get_by_placeholder("user@example.com").fill(email)
    page.get_by_placeholder("initial password").fill(password)
    page.get_by_placeholder("Jane Doe").fill("Manual UI Check")
    page.get_by_placeholder("0", exact=True).fill("3")
    page.get_by_role("button", name="Create user").click()

    # wait for the new row to show up in the table
    page.wait_for_selector(f"text={email}", timeout=15000)
    row = page.locator("tr", has_text=email)
    print(f"row visible: {row.count() > 0}")
    if row.count() == 0:
        fail.append("row missing after create")

    page.screenshot(path=str(SHOT), full_page=True)
    browser.close()

if errors:
    fail.append(f"pageerrors: {errors[:3]}")

# cleanup: delete auth user (cascades) via direct SQL
import psycopg  # noqa: E402

conn = psycopg.connect(env["DB_URL"])
cur = conn.cursor()
cur.execute("select id from auth.users where email = %s", (email,))
hit = cur.fetchone()
if hit:
    cur.execute("delete from auth.users where id = %s", (hit[0],))
conn.commit()
conn.close()
print(f"cleanup: {'deleted' if hit else 'user not found'}")
if not hit:
    fail.append("user not in auth.users after UI create")

if fail:
    print("FAIL:", "; ".join(fail))
    raise SystemExit(1)
print("PASS: admin create-user UI end-to-end")
