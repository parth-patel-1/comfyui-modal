"""Verify create_generation maps RPC errors to proper HTTP status (429, not 500)."""
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB_URL = "https://egimurphizmxkckabslx.supabase.co"
SB_KEY = "sb_publishable_5CVRJZYxbJwqp1UgWq8vyg_TPLnzioK"
BACKEND = "http://localhost:8900"

creds = json.loads((ROOT / "scripts" / ".testuser").read_text())
req = urllib.request.Request(
    f"{SB_URL}/auth/v1/token?grant_type=password",
    data=json.dumps({"email": creds["email"], "password": creds["password"]}).encode(),
    headers={"apikey": SB_KEY, "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=20) as r:
    tok = json.load(r)["access_token"]

def post_gen():
    body = json.dumps({
        "engine": "image", "mode": "t2i", "prompt": "429 mapping check",
        "negative_prompt": "", "reference_paths": [],
        "params": {"width": 512, "height": 512, "steps": 4, "cfg": 1},
    }).encode()
    req = urllib.request.Request(
        f"{BACKEND}/api/generations", data=body, method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

s1, g1 = post_gen()
s2, b2 = post_gen()
print(f"first job: {s1} {g1.get('status')} id={g1.get('id', '')[:8]}")
print(f"second job: {s2} detail={b2.get('detail')}")

# cleanup: cancel whatever we created
if s1 == 201:
    req = urllib.request.Request(f"{BACKEND}/api/generations/{g1['id']}/cancel",
                                 method="POST", headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        print("cleanup:", json.load(r))

ok = s1 == 201 and s2 == 429
print("RESULT:", "PASS" if ok else "FAIL")
