"""Live check: submitted job's progress must climb (10 -> 20 -> 40 -> ... -> 100).

Requires the worker to be running (python -m app.worker.loop from backend/).
Creates one small image job, polls /api/generations/{id} until terminal, and
prints every distinct (status, progress) pair it observes.
"""
import json
import time
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
HDR = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

body = json.dumps({
    "engine": "image", "mode": "t2i", "prompt": "progress ladder check",
    "negative_prompt": "", "reference_paths": [],
    "params": {"width": 512, "height": 512, "steps": 4, "cfg": 1},
}).encode()
req = urllib.request.Request(f"{BACKEND}/api/generations", data=body, method="POST", headers=HDR)
with urllib.request.urlopen(req, timeout=20) as r:
    gen = json.load(r)
gid = gen["id"]
print(f"created {gid[:8]} status={gen['status']} progress={gen['progress']} "
      f"started_at={gen.get('started_at')!r}")

seen: list[tuple[str, int]] = []
terminal = ("succeeded", "failed", "canceled")
deadline = time.time() + 600  # engine may be cold; worker retries up to 900s
status, progress = gen["status"], gen["progress"]
while time.time() < deadline:
    if (status, progress) not in seen:
        seen.append((status, progress))
        print(f"  t+{int(time.time() - (deadline - 600)):>3}s  {status}  {progress}%")
    if status in terminal:
        break
    time.sleep(2)
    req = urllib.request.Request(f"{BACKEND}/api/generations/{gid}", headers=HDR)
    with urllib.request.urlopen(req, timeout=20) as r:
        g = json.load(r)
    status, progress = g["status"], g["progress"]

print("final:", status, progress, "error:", g.get("error"))
climbed = any(p > 0 for _, p in seen)
ok = status == "succeeded" and climbed and seen[-1] == ("succeeded", 100)
print("seen ladder:", " -> ".join(f"{s}:{p}" for s, p in seen))
print("RESULT:", "PASS" if ok else "FAIL")
