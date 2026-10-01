"""Cancel any stale active generations for the test user (frees job slots)."""
import json
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

req = urllib.request.Request(f"{BACKEND}/api/generations?limit=20",
                             headers={"Authorization": f"Bearer {tok}"})
gens = json.load(urllib.request.urlopen(req, timeout=20))
for g in gens:
    if g["status"] in ("queued", "provisioning", "running", "uploading"):
        req = urllib.request.Request(
            f"{BACKEND}/api/generations/{g['id']}/cancel", method="POST",
            headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                print(g["id"][:8], g["status"], "->", json.load(r))
        except Exception as e:
            print(g["id"][:8], g["status"], "-> cancel failed:", e)
