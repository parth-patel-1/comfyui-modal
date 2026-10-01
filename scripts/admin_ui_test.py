"""Local Playwright UI test for the GenStudio admin panel (no tunnel / no browserless).

Checks, against the locally running stack (frontend :3000, backend :8900):
  1. Unauthenticated /admin is blocked (role guard) and does not leak admin data.
  2. Authenticated as an admin (session injected into localStorage, same mechanism
     supabase-js uses), all 5 admin tabs render their expected content.

Run:  python scripts/admin_ui_test.py
Artifacts: screenshots saved to <repo>/_pw_shots/<tab>.png
"""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = "http://localhost:3000"
SB_URL = "https://egimurphizmxkckabslx.supabase.co"
SB_KEY = "sb_publishable_5CVRJZYxbJwqp1UgWq8vyg_TPLnzioK"
STORAGE_KEY = "sb-egimurphizmxkckabslx-auth-token"
SHOT_DIR = ROOT / "_pw_shots"
SETTLE_MS = 500  # extra settle after network idle

def wait_ready(page, timeout: int = 20000) -> None:
    """Wait until client fetches are done: network idle and no spinner left."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    try:
        page.wait_for_function(
            "() => !document.querySelector('.animate-spin')", timeout=timeout
        )
    except Exception:
        pass
    page.wait_for_timeout(SETTLE_MS)

TABS = [
    # (name, path, list of substrings that must appear in body text)
    ("overview", "/admin", ["Credits in circulation", "Last deploy"]),
    ("users", "/admin/users", ["Search", "tester@genstudio.dev"]),
    ("settings", "/admin/settings", ["Site settings"]),
    ("engines", "/admin/engines", ["Engine infrastructure", "Deploy"]),
    ("audit", "/admin/audit", ["Admin actions (newest first)"]),
]


def supabase_login(email: str, password: str) -> dict:
    req = urllib.request.Request(
        f"{SB_URL}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"apikey": SB_KEY, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def body_text(page) -> str:
    return page.evaluate("() => (document.body ? document.body.innerText : '')")


def snap(page, path: Path) -> None:
    """Screenshot with one retry (transient Errno 22 on Windows file locks)."""
    for attempt in range(2):
        try:
            page.screenshot(path=str(path))
            return
        except OSError:
            if attempt:
                raise
            page.wait_for_timeout(500)


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    creds = json.loads((ROOT / "scripts" / ".testuser").read_text())
    session = supabase_login(creds["email"], creds["password"])
    print(f"Supabase login OK: {session['user']['email']}")

    failures = 0
    SHOT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ---- 1. negative test: no session -> role guard must block ----------
        print("\n[1] Unauthenticated guard")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(f"{FRONTEND}/admin", wait_until="load", timeout=20000)
        wait_ready(page)
        text = body_text(page)
        failures += 0 if check(
            "/admin blocked without session",
            "Admin access required" in text or "/login" in page.url,
            f"url={page.url}",
        ) else 1
        failures += 0 if check(
            "no admin data leaked", "Engine infrastructure" not in text
        ) else 1
        page.screenshot(path=str(SHOT_DIR / "guard_unauthenticated.png"))
        ctx.close()

        # ---- 2. authenticated pass over all 5 tabs --------------------------
        print("\n[2] Authenticated admin tabs")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        token = json.dumps(session)  # same shape supabase-js persists
        ctx.add_init_script(
            f"window.localStorage.setItem({STORAGE_KEY!r}, {token!r});"
        )
        page = ctx.new_page()
        page.on("pageerror", lambda e: print(f"  [pageerror] {e}"))

        for name, path, markers in TABS:
            page.goto(f"{FRONTEND}{path}", wait_until="load", timeout=20000)
            wait_ready(page)
            text = body_text(page)
            print(f" {name} ({path}):")
            if not check("guard not triggered", "Admin access required" not in text):
                failures += 1
            if not check("no redirect away", page.url.rstrip("/").endswith(path)):
                failures += 1
            for m in markers:
                if not check(f"shows {m!r}", m.lower() in text.lower()):
                    failures += 1
            snap(page, SHOT_DIR / f"{name}.png")

        ctx.close()
        browser.close()

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    print(f"Screenshots: {SHOT_DIR}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
