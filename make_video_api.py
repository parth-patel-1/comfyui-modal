"""Generate a MiniMax H3 text-to-video clip via the deployed ComfyUI HTTP API.

Submits workflows/minimax_h3_t2v_api.json to the Modal-hosted ComfyUI server,
polls /history until the prompt finishes, then downloads the MP4 into the
local output/ folder.

Usage:
    python make_video_api.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://patelparth268268--comfyui.modal.run"
WORKFLOW_PATH = Path(__file__).parent / "workflows" / "minimax_h3_t2v_api.json"
OUTPUT_DIR = Path(__file__).parent / "output"
SAVE_NODE_ID = "14"  # SaveVideo node in the API workflow

POLL_INTERVAL_S = 15
MAX_WAIT_S = 60 * 60  # cold start + 42 GB model load + sampling can be slow


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    log(f"Loaded {WORKFLOW_PATH.name} ({len(workflow)} nodes)")
    assert "15" in workflow and workflow["15"]["class_type"] == "MiniMaxH3SigmaShift"

    # --- submit -------------------------------------------------------------
    log(f"POST {BASE_URL}/prompt ...")
    resp = requests.post(
        f"{BASE_URL}/prompt",
        json={"prompt": workflow},
        timeout=(30, 30 * 60),  # a cold container may take minutes to accept
    )
    if resp.status_code != 200:
        log(f"ERROR: /prompt returned {resp.status_code}: {resp.text[:2000]}")
        return 1
    payload = resp.json()
    node_errors = payload.get("node_errors") or {}
    if node_errors:
        log(f"ERROR: node validation failed: {json.dumps(node_errors, indent=2)}")
        return 1
    prompt_id = payload["prompt_id"]
    log(f"Queued prompt_id={prompt_id} (queue number {payload.get('number')})")

    # --- poll history ---------------------------------------------------------
    deadline = time.time() + MAX_WAIT_S
    while time.time() < deadline:
        try:
            hist = requests.get(f"{BASE_URL}/history/{prompt_id}", timeout=60).json()
        except requests.RequestException as e:
            log(f"history poll error (retrying): {e}")
            time.sleep(POLL_INTERVAL_S)
            continue
        entry = hist.get(prompt_id)
        if entry:
            status = entry.get("status", {})
            status_str = status.get("status_str")
            if status.get("completed") or status_str in ("success", "error"):
                if status_str != "success":
                    log(f"ERROR: prompt finished with status: {json.dumps(status)[:2000]}")
                    for msg in status.get("messages", []):
                        log(f"  {msg}")
                    return 1
                outputs = entry.get("outputs", {})
                save_out = outputs.get(SAVE_NODE_ID, {})
                files = (
                    save_out.get("videos")
                    or save_out.get("gifs")
                    or save_out.get("images")  # SaveVideo reports under "images"
                    or []
                )
                if not files:
                    log(f"ERROR: no video in outputs of node {SAVE_NODE_ID}: {json.dumps(outputs)[:2000]}")
                    return 1
                OUTPUT_DIR.mkdir(exist_ok=True)
                for f in files:
                    params = {
                        "filename": f["filename"],
                        "subfolder": f.get("subfolder", ""),
                        "type": f.get("type", "output"),
                    }
                    log(f"Downloading {f['filename']} ...")
                    vid = requests.get(f"{BASE_URL}/view", params=params, timeout=600)
                    vid.raise_for_status()
                    dest = OUTPUT_DIR / f["filename"]
                    dest.write_bytes(vid.content)
                    log(f"Saved {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
                log("DONE")
                return 0
        else:
            # report queue position for visibility
            try:
                q = requests.get(f"{BASE_URL}/queue", timeout=30).json()
                running = len(q.get("queue_running", []))
                pending = len(q.get("queue_pending", []))
                log(f"still running... (running={running} pending={pending})")
            except requests.RequestException:
                log("still running... (queue probe failed)")
        time.sleep(POLL_INTERVAL_S)
    log("ERROR: timed out waiting for the prompt to finish")
    return 1


if __name__ == "__main__":
    sys.exit(main())
