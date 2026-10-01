"""Regression: the Studio status card shows a live, climbing percentage.

Submits a real image generation through the UI, then samples the badge
percentage at least twice while the job runs and verifies it increases,
ends at Done 100, and unlocks the composer.

Run:  python scripts/_studio_progress_ui.py   (worker must be running)
Artifacts: _pw_shots/studio_progress_ui.png
"""
import json
import re
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
SHOT = ROOT / "_pw_shots" / "studio_progress_ui.png"

creds = json.loads((ROOT / "scripts" / ".testuser").read_text())

req = urllib.request.Request(
    f"{SB_URL}/auth/v1/token?grant_type=password",
    data=json.dumps({"email": creds["email"], "password": creds["password"]}).encode(),
    headers={"apikey": SB_KEY, "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=20) as r:
    session = json.load(r)
token = session["access_token"]

prompt = f"progress ui check {int(time.time())}"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(
        f"window.localStorage.setItem({STORAGE_KEY!r}, {json.dumps(session)!r});"
    )
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(f"{FRONTEND}/studio", wait_until="load", timeout=20000)
    box = page.get_by_placeholder("Describe the image")
    box.fill(prompt)
    page.get_by_role("button", name="Generate").click()
    print(f"submitted: {prompt}")

    # sample the status badge percentage over time; the backend is the
    # source of truth for termination (old cards also render "Done")
    pct_re = re.compile(r"(Queued|Starting GPU|Generating|Saving results)[^\d]*(\d+)%")
    samples: list[tuple[str, int]] = []
    done = False
    backend = None
    deadline = time.monotonic() + 420
    while time.monotonic() < deadline:
        text = page.evaluate("() => document.body.innerText")
        m = pct_re.search(text)
        if m:
            label, pct = m.group(1), int(m.group(2))
            if not samples or samples[-1] != (label, pct):
                samples.append((label, pct))
                print(f"  {label} {pct}%")
        req = urllib.request.Request(
            f"{BACKEND}/api/generations?limit=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            latest = json.load(r)[0]
        if latest["prompt"] == prompt and latest["status"] == "succeeded":
            done = True
            backend = (latest["status"], latest["progress"])
            break
        if latest["status"] in ("failed", "canceled"):
            backend = (latest["status"], latest["progress"])
            break
        page.wait_for_timeout(1000)

    page.screenshot(path=str(SHOT))
    unlocked = not page.get_by_role("button", name="Generate").is_disabled()
    print(f"done badge shown={done}, generate unlocked={unlocked}, backend={backend}")
    print(f"pageerrors: {errors or 'none'}")
    browser.close()

# percentage must have been observed increasing during the run
pcts = [pct for _, pct in samples]
climbed = any(b > a for a, b in zip(pcts, pcts[1:]))
ok = done and climbed and unlocked and not errors \
    and (backend is None or backend == ("succeeded", 100))
print("samples:", samples)
print("RESULT:", "PASS" if ok else "FAIL")