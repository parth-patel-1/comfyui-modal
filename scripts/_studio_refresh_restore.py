"""Regression: an in-flight generation survives a Studio page refresh.

Creates a real image generation via the backend API, then verifies in the
browser that the queued/running job (prompt bubble + live status card) is
still shown after page.reload(), that the composer stays locked while it
runs, and that it unlocks again once the job reaches a terminal state.

Run:  python scripts/_studio_refresh_restore.py
Artifacts: _pw_shots/studio_refresh_restore.png
"""
import json
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = "http://localhost:3000"
BACKEND = "http://localhost:8900"
SB_URL = "https://egimurphizmxkckabslx.supabase.co"
SB_KEY = "sb_publishable_5CVRJZYxbJwqp1UgWq8vyg_TPLnzioK"
STORAGE_KEY = "sb-egimurphizmxkckabslx-auth-token"
SHOT = ROOT / "_pw_shots" / "studio_refresh_restore.png"

ACTIVE_LABELS = ("Queued", "Starting GPU", "Generating", "Saving results")
TERMINAL_LABELS = ("Done", "Failed", "Canceled")

creds = json.loads((ROOT / "scripts" / ".testuser").read_text())

req = urllib.request.Request(
    f"{SB_URL}/auth/v1/token?grant_type=password",
    data=json.dumps({"email": creds["email"], "password": creds["password"]}).encode(),
    headers={"apikey": SB_KEY, "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=20) as r:
    session = json.load(r)
token = session["access_token"]


def api(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BACKEND}{path}",
        data=json.dumps(payload).encode() if payload else None,
        method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def gen_status(gen_id: str) -> str:
    return api(f"/api/generations/{gen_id}")["status"]


prompt = f"refresh restore check {int(time.time())}"
gen = api("/api/generations", "POST", {
    "engine": "image", "mode": "t2i", "prompt": prompt,
    "negative_prompt": "", "reference_paths": [],
    "params": {"width": 512, "height": 512, "steps": 4, "cfg": 1},
})
gen_id = gen["id"]
print(f"created generation {gen_id[:8]} status={gen['status']}")
assert gen["status"] in ("queued", "provisioning", "running")


def active_shown(page) -> bool:
    text = page.evaluate("() => document.body.innerText")
    has_prompt = prompt in text
    has_active = any(lbl in text for lbl in ACTIVE_LABELS)
    return has_prompt and has_active


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(
        f"window.localStorage.setItem({STORAGE_KEY!r}, {json.dumps(session)!r});"
    )
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    gen_btn = page.get_by_role("button", name="Generate")

    # 1) fresh visit: the just-created job must appear immediately
    page.goto(f"{FRONTEND}/studio", wait_until="load", timeout=20000)
    try:
        page.get_by_text(prompt).first.wait_for(timeout=15000)
    except Exception:
        print(f"job did not appear on fresh load; backend status={gen_status(gen_id)}")
        raise SystemExit("RESULT: FAIL")
    before_reload = active_shown(page)
    locked_before = gen_btn.is_disabled()
    print(f"before reload: active card shown={before_reload}, generate locked={locked_before}")

    # 2) the user refreshes mid-generation: prompt must still be in the queue
    page.reload(wait_until="load")
    try:
        page.get_by_text(prompt).first.wait_for(timeout=15000)
    except Exception:
        print(f"job lost after reload; backend status={gen_status(gen_id)}")
        raise SystemExit("RESULT: FAIL")
    after_reload = active_shown(page)
    locked_after = gen_btn.is_disabled()
    print(f"after reload:  active card shown={after_reload}, generate locked={locked_after}")
    page.screenshot(path=str(SHOT))

    # 3) try to cancel while cancelable; otherwise wait for any terminal state
    try:
        page.get_by_role("button", name="Cancel").click(timeout=3000)
        print("clicked Cancel")
    except Exception:
        pass
    deadline = time.monotonic() + 240
    terminal = False
    while time.monotonic() < deadline:
        text = page.evaluate("() => document.body.innerText")
        if any(lbl in text for lbl in TERMINAL_LABELS) and prompt in text \
                and not gen_btn.is_disabled():
            terminal = True
            break
        page.wait_for_timeout(2000)
    unlocked = not gen_btn.is_disabled()
    final_status = gen_status(gen_id)
    print(f"terminal reached={terminal}, status={final_status}, generate unlocked={unlocked}")
    print(f"pageerrors: {errors or 'none'}")
    browser.close()

ok = before_reload and locked_before and after_reload and locked_after \
    and terminal and unlocked and not errors
print("RESULT:", "PASS" if ok else "FAIL")
