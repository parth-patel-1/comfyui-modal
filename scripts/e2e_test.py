"""End-to-end API + worker test.

Login as the test user, create a t2i job via the API, then (separately)
the worker picks it up. This script covers the API side and polls the
job to completion if the worker is running.

Usage: python scripts/e2e_test.py [--no-submit]
"""

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent.parent
BASE = "http://127.0.0.1:8900"


def main() -> None:
    creds = json.loads((ROOT / "scripts" / ".testuser").read_text())
    env = dict(
        line.split("=", 1)
        for line in (ROOT / "backend" / ".env").read_text().splitlines()
        if "=" in line
    )
    anon = env["SUPABASE_ANON_KEY"]

    r = httpx.post(
        f"{env['SUPABASE_URL']}/auth/v1/token?grant_type=password",
        json={"email": creds["email"], "password": creds["password"]},
        headers={"apikey": anon},
        timeout=30,
    )
    if r.status_code != 200:
        sys.exit(f"login failed: {r.status_code} {r.text[:200]}")
    token = r.json()["access_token"]
    hdr = {"Authorization": f"Bearer {token}"}
    print("login OK")

    wallet = httpx.get(f"{BASE}/api/wallet", headers=hdr, timeout=15).json()
    print("wallet:", wallet)
    assert wallet["balance"] >= 5, "not enough credits for the test"

    est = httpx.get(
        f"{BASE}/api/config/estimate", headers=hdr,
        params={"engine": "image", "width": 1024, "height": 1024}, timeout=15,
    ).json()
    print("estimate (1024x1024 t2i):", est)

    job = httpx.post(
        f"{BASE}/api/generations", headers=hdr,
        json={
            "engine": "image",
            "mode": "t2i",
            "prompt": "a small red cube on a white table, soft studio light",
            "params": {"width": 1024, "height": 1024},
        },
        timeout=30,
    )
    print("create:", job.status_code, json.dumps(job.json(), default=str)[:300])
    if job.status_code == 402:
        print("(insufficient credits -- top up and rerun)")
        return
    job.raise_for_status()
    gen = job.json()
    gid = gen["id"]

    wallet_after = httpx.get(f"{BASE}/api/wallet", headers=hdr, timeout=15).json()
    print("wallet after debit:", wallet_after)
    assert wallet_after["balance"] == wallet["balance"] - gen["credits_charged"]

    print(f"polling job {gid} (is the worker running?)...")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        time.sleep(5)
        g = httpx.get(f"{BASE}/api/generations/{gid}", headers=hdr, timeout=15).json()
        print("  status:", g["status"], g["progress"], g["error"][:80] if g["error"] else "")
        if g["status"] in ("succeeded", "failed", "canceled"):
            break
    print("final:", g["status"], "| outputs:", g["output_paths"])

    wallet_end = httpx.get(f"{BASE}/api/wallet", headers=hdr, timeout=15).json()
    print("wallet end:", wallet_end["balance"])
    if g["status"] == "succeeded":
        assert wallet_end["balance"] == wallet_after["balance"]
        assert g["output_paths"], "no outputs recorded"
        print("E2E PASSED (succeeded, no refund)")
    else:
        assert wallet_end["balance"] == wallet["balance"], "refund missing"
        print("E2E PASSED (failed with full refund)")


if __name__ == "__main__":
    main()
