"""Phase 1 smoke test for the GenStudio Modal engines.

Usage: python scripts/smoke_engine.py <image_url> <video_url> <token>
"""

import json
import sys

import requests

TIMEOUT = (30, 1800)


def main() -> None:
    image_url, video_url, token = sys.argv[1], sys.argv[2], sys.argv[3]
    hdr = {"Authorization": f"Bearer {token}"}

    # 1) no token -> 401
    r = requests.get(f"{image_url}/api/object_info", timeout=TIMEOUT)
    print("no-token status:", r.status_code, "(expect 401)")
    assert r.status_code == 401, r.text[:200]

    # 2) bad token -> 401
    r = requests.get(f"{image_url}/api/object_info",
                     headers={"Authorization": "Bearer wrong"}, timeout=TIMEOUT)
    print("bad-token status:", r.status_code, "(expect 401)")
    assert r.status_code == 401

    # 3) good token -> object_info (cold start may take minutes)
    print("probing image engine (cold start possible, be patient)...")
    r = requests.get(f"{image_url}/api/object_info", headers=hdr, timeout=TIMEOUT)
    print("image object_info:", r.status_code, "(expect 200)")
    assert r.status_code == 200, r.text[:300]

    # 4) verify MiniMaxH3ImageToVideo i2v input names on the video engine
    import time

    print("probing video engine (cold start possible)...")
    rv = None
    for _ in range(60):  # up to ~10 min for cold start
        rv = requests.get(f"{video_url}/api/object_info/MiniMaxH3ImageToVideo",
                          headers=hdr, timeout=TIMEOUT)
        if rv.status_code == 200:
            break
        print("  video engine not ready:", rv.status_code, rv.text[:60])
        time.sleep(10)
    print("video node info:", rv.status_code)
    assert rv.status_code == 200, rv.text[:300]
    node = rv.json()["MiniMaxH3ImageToVideo"]
    schema = node["input"]["optional"]
    print("optional inputs:", sorted(schema))
    assert "first_frame" in schema and "last_frame" in schema

    # 5) submit a tiny t2i job end-to-end on the image engine
    template = json.loads(
        (path := __import__("pathlib").Path(__file__).parent.parent
         / "modal_app" / "workflows" / "qwen_image_2.1_api.json").read_text()
    )
    template["6"]["inputs"]["text"] = "a small red cube on white background, studio light"
    rp = requests.post(f"{image_url}/prompt", headers=hdr,
                       json={"prompt": template}, timeout=TIMEOUT)
    print("t2i /prompt:", rp.status_code)
    assert rp.status_code == 200, rp.text[:500]
    prompt_id = rp.json()["prompt_id"]
    print("prompt_id:", prompt_id)

    for _ in range(180):  # up to ~15 min
        time.sleep(5)
        rh = requests.get(f"{image_url}/history/{prompt_id}", headers=hdr, timeout=TIMEOUT)
        entry = rh.json().get(prompt_id)
        if entry and entry.get("status", {}).get("completed"):
            status = entry["status"]
            print("t2i status:", status.get("status_str"))
            outputs = entry.get("outputs", {})
            for nid, out in outputs.items():
                for img in out.get("images", []):
                    print("  output:", nid, img["filename"], img.get("subfolder"))
            assert status.get("status_str") == "success", status
            break
    else:
        raise SystemExit("t2i generation timed out")

    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
