"""Regression: pasting a screenshot in the Studio attaches it as a reference.

Writes a PNG into the browser clipboard, presses Ctrl+V on the studio page
and verifies the composer auto-switches from t2i -> edit, uploads the image
(intercepts the upload ticket to learn the storage path) and shows the
reference chip. Cleans up the uploaded storage object afterwards.

Run:  python scripts/_paste_ref_check.py
Artifacts: _pw_shots/paste_ref_ui.png
"""
import json
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = "http://localhost:3000"
SB_URL = "https://egimurphizmxkckabslx.supabase.co"
SB_KEY = "sb_publishable_5CVRJZYxbJwqp1UgWq8vyg_TPLnzioK"
STORAGE_KEY = "sb-egimurphizmxkckabslx-auth-token"
SHOT = ROOT / "_pw_shots" / "paste_ref_ui.png"

# 1x1 red PNG
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

creds = json.loads((ROOT / "scripts" / ".testuser").read_text())
req = urllib.request.Request(
    f"{SB_URL}/auth/v1/token?grant_type=password",
    data=json.dumps({"email": creds["email"], "password": creds["password"]}).encode(),
    headers={"apikey": SB_KEY, "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=20) as r:
    session = json.load(r)
token = session["access_token"]

tickets: list[dict] = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=FRONTEND)
    ctx.add_init_script(
        f"window.localStorage.setItem({STORAGE_KEY!r}, {json.dumps(session)!r});"
    )
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(f"{FRONTEND}/studio", wait_until="load", timeout=20000)
    box = page.get_by_placeholder("Describe the image")
    box.wait_for(timeout=15000)
    mode_before = page.get_by_label("Generation mode").input_value()
    print(f"mode before paste: {mode_before}")

    # put the PNG on the (real) browser clipboard, then paste
    page.evaluate(
        """async (b64) => {
            const bin = atob(b64);
            const buf = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
            await navigator.clipboard.write([new ClipboardItem(
                { "image/png": new Blob([buf], { type: "image/png" }) })]);
        }""",
        PNG_B64,
    )
    box.click()
    with page.expect_response(
        lambda r: "/api/uploads/ticket" in r.url, timeout=15000
    ) as resp_info:
        page.keyboard.press("Control+V")
    tickets.append(json.loads(resp_info.value.body()))

    mode_after = ""
    chip_visible = False
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        mode_after = page.get_by_label("Generation mode").input_value()
        # the chip is the only place with a "Remove reference" button
        chip_visible = page.get_by_label("Remove reference").count() > 0
        if chip_visible and mode_after != mode_before:
            break
        page.wait_for_timeout(300)
    print(f"chip visible: {chip_visible}")

    page.screenshot(path=str(SHOT))
    browser.close()

# cleanup: remove the uploaded storage object with the user's JWT
cleaned = False
for t in tickets:
    try:
        del_req = urllib.request.Request(
            f"{SB_URL}/storage/v1/object/{t['bucket']}/{t['path']}",
            method="DELETE",
            headers={"apikey": SB_KEY, "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(del_req, timeout=20) as r:
            cleaned = r.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"cleanup failed for {t['path']}: {e.code} {e.read().decode()[:200]}")
    except Exception as exc:  # noqa: BLE001
        print(f"cleanup failed for {t['path']}: {exc}")
print(f"tickets: {tickets}")
print(f"mode {mode_before!r} -> {mode_after!r}, chip={chip_visible}, cleaned={cleaned}")
ok = (
    mode_before == "t2i"
    and mode_after == "edit"
    and chip_visible
    and len(tickets) == 1
    and cleaned
    and not errors
)
print(f"pageerrors: {errors or 'none'}")
print("RESULT:", "PASS" if ok else "FAIL")
