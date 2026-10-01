"""One-off check: toggle Studio engine image -> video without crashing."""
import json
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SB_URL = "https://egimurphizmxkckabslx.supabase.co"
SB_KEY = "sb_publishable_5CVRJZYxbJwqp1UgWq8vyg_TPLnzioK"
STORAGE_KEY = "sb-egimurphizmxkckabslx-auth-token"

creds = json.loads((ROOT / "scripts" / ".testuser").read_text())
req = urllib.request.Request(
    f"{SB_URL}/auth/v1/token?grant_type=password",
    data=json.dumps({"email": creds["email"], "password": creds["password"]}).encode(),
    headers={"apikey": SB_KEY, "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=20) as r:
    session = json.load(r)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(
        f"window.localStorage.setItem({STORAGE_KEY!r}, {json.dumps(session)!r});"
    )
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://localhost:3000/studio", wait_until="load", timeout=20000)
    page.wait_for_load_state("networkidle", timeout=20000)
    page.get_by_role("button", name="Video").click()
    page.wait_for_timeout(1500)
    text = page.evaluate("() => document.body.innerText")
    ph = page.get_by_label("Prompt").get_attribute("placeholder") or ""
    ok_placeholder = ph.startswith("Describe the video")
    ok_mode = "Text -> Video" in text
    ok_no_err = "couldn" not in text.lower() and "Studio unavailable" not in text
    print(f"video placeholder shown: {ok_placeholder}")
    print(f"mode select = Text -> Video: {ok_mode}")
    print(f"no error boundary: {ok_no_err}")
    print(f"pageerrors: {errors or 'none'}")
    page.screenshot(path=str(ROOT / "_pw_shots" / "studio_video_toggle.png"))
    browser.close()
    print("RESULT:", "PASS" if ok_placeholder and ok_mode and ok_no_err and not errors else "FAIL")
