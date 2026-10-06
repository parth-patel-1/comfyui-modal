"""Batch-generate portrait MiniMax H3 text-to-video shorts via the Modal ComfyUI API.

Reads every .txt prompt in prompts/, injects each into
workflows/minimax_h3_t2v_api.json (node 5: MiniMaxH3ImageToVideo) with a
1-megapixel-class portrait resolution (720x1280, 9:16) and a 15-second length
(360 frames @ 24 fps), then submits all jobs to the Modal-hosted ComfyUI queue
and downloads the finished MP4s into output/shorts/.

Jobs are queued server-side on Modal, so generation continues on the GPU
container even if this script is stopped; rerunning it skips prompts whose
videos were already downloaded.

Usage (foreground):
    python generate_shorts_api.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://patelparth268268--comfyui.modal.run"
WORKFLOW_PATH = Path(__file__).parent / "workflows" / "minimax_h3_t2v_api.json"
PROMPTS_DIR = Path(__file__).parent / "prompts"
OUTPUT_DIR = Path(__file__).parent / "output" / "shorts"

PROMPT_NODE_ID = "5"   # MiniMaxH3ImageToVideo: prompt / width / height / length
NOISE_NODE_ID = "6"    # RandomNoise: noise_seed
SAVE_NODE_ID = "14"    # SaveVideo

# --- generation config -------------------------------------------------------
# 1 MP portrait: 9:16 with ~1,000,000 pixels, both sides divisible by 16
# (video VAE requirement). 720x1280 = 0.92 MP -- the standard 1MP-class
# portrait/shorts resolution.
WIDTH = 720
HEIGHT = 1280
FPS = 24
DURATION_S = 15
LENGTH = FPS * DURATION_S  # 360 frames

POLL_INTERVAL_S = 15
MAX_WAIT_S = 4 * 60 * 60  # cold start + 42 GB model load + 5x 15s @ 1MP sampling



def load_prompts() -> list[Path]:
    files = sorted(PROMPTS_DIR.glob("*.txt"))
    if not files:
        log(f"ERROR: no .txt prompt files found in {PROMPTS_DIR}")
    return files


def build_workflow(prompt_text: str, seed: int) -> dict:
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    node = workflow[PROMPT_NODE_ID]
    assert node["class_type"] == "MiniMaxH3ImageToVideo"
    node["inputs"]["prompt"] = prompt_text
    node["inputs"]["width"] = WIDTH
    node["inputs"]["height"] = HEIGHT
    node["inputs"]["length"] = LENGTH
    workflow[NOISE_NODE_ID]["inputs"]["noise_seed"] = seed
    return workflow


def submit(prompt_file: Path) -> str | None:
    """POST one workflow to the queue; returns prompt_id or None on failure."""
    text = prompt_file.read_text(encoding="utf-8").strip()
    seed = int(hashlib.sha256(prompt_file.stem.encode()).hexdigest()[:8], 16)
    workflow = build_workflow(text, seed)
    log(f"POST {prompt_file.name} (seed={seed}, {WIDTH}x{HEIGHT}, "
        f"{LENGTH} frames = {DURATION_S}s) ...")
    try:
        resp = requests.post(
            f"{BASE_URL}/prompt",
            json={"prompt": workflow},
            timeout=(30, 30 * 60),  # a cold container may take minutes to accept
        )
    except requests.RequestException as e:
        log(f"ERROR: submit failed for {prompt_file.name}: {e}")
        return None
    if resp.status_code != 200:
        log(f"ERROR: /prompt returned {resp.status_code}: {resp.text[:2000]}")
        return None
    payload = resp.json()
    node_errors = payload.get("node_errors") or {}
    if node_errors:
        log(f"ERROR: node validation failed for {prompt_file.name}: "
            f"{json.dumps(node_errors, indent=2)[:2000]}")
        return None
    prompt_id = payload["prompt_id"]
    log(f"Queued {prompt_file.name} -> prompt_id={prompt_id} "
        f"(queue number {payload.get('number')})")
    return prompt_id



def download_video(files: list[dict], dest: Path) -> bool:
    for f in files:
        params = {
            "filename": f["filename"],
            "subfolder": f.get("subfolder", ""),
            "type": f.get("type", "output"),
        }
        log(f"Downloading {f['filename']} ...")
        try:
            vid = requests.get(f"{BASE_URL}/view", params=params, timeout=600)
            vid.raise_for_status()
        except requests.RequestException as e:
            log(f"ERROR: download failed: {e}")
            return False
        dest.write_bytes(vid.content)
        log(f"Saved {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return True


def poll_and_download(jobs: dict[str, Path]) -> int:
    """Poll history for each prompt_id; returns number of videos saved."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pending = dict(jobs)
    saved = 0
    deadline = time.time() + MAX_WAIT_S
    while pending and time.time() < deadline:
        for prompt_id, prompt_file in list(pending.items()):
            try:
                hist = requests.get(f"{BASE_URL}/history/{prompt_id}",
                                    timeout=60).json()
            except requests.RequestException as e:
                log(f"history poll error for {prompt_file.name} (retrying): {e}")
                continue
            entry = hist.get(prompt_id)
            if not entry:
                continue
            status = entry.get("status", {})
            status_str = status.get("status_str")
            if not (status.get("completed") or status_str in ("success", "error")):
                continue
            if status_str != "success":
                log(f"ERROR: {prompt_file.name} finished with status: "
                    f"{json.dumps(status)[:2000]}")
                for msg in status.get("messages", []):
                    log(f"  {msg}")
                del pending[prompt_id]
                continue
            outputs = entry.get("outputs", {})
            save_out = outputs.get(SAVE_NODE_ID, {})
            files = (
                save_out.get("videos")
                or save_out.get("gifs")
                or save_out.get("images")  # SaveVideo reports under "images"
                or []
            )
            if not files:
                log(f"ERROR: no video in outputs of node {SAVE_NODE_ID} for "
                    f"{prompt_file.name}: {json.dumps(outputs)[:2000]}")
                del pending[prompt_id]
                continue
            dest = OUTPUT_DIR / f"{prompt_file.stem}.mp4"
            if download_video(files, dest):
                saved += 1
            del pending[prompt_id]
        if pending:
            try:
                q = requests.get(f"{BASE_URL}/queue", timeout=30).json()
                log(f"waiting... {len(pending)} job(s) left on server "
                    f"(running={len(q.get('queue_running', []))} "
                    f"pending={len(q.get('queue_pending', []))})")
            except requests.RequestException:
                log(f"waiting... {len(pending)} job(s) left on server")
            time.sleep(POLL_INTERVAL_S)
    for prompt_id, prompt_file in pending.items():
        log(f"ERROR: timed out waiting for {prompt_file.name} ({prompt_id})")
    return saved


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)



def main() -> int:
    prompt_files = load_prompts()
    if not prompt_files:
        return 1
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Skip prompts whose videos were already downloaded (rerun safety).
    todo = [p for p in prompt_files if not (OUTPUT_DIR / f"{p.stem}.mp4").exists()]
    for p in prompt_files:
        if (OUTPUT_DIR / f"{p.stem}.mp4").exists():
            log(f"Skipping {p.name} -- already downloaded.")
    if not todo:
        log("All videos already present. Nothing to do.")
        return 0

    log(f"Submitting {len(todo)} job(s) to {BASE_URL} ...")
    jobs: dict[str, Path] = {}
    failed_submits = 0
    for p in todo:
        prompt_id = submit(p)
        if prompt_id:
            jobs[prompt_id] = p
        else:
            failed_submits += 1
    log(f"Submitted {len(jobs)} job(s); {failed_submits} submit failure(s).")
    if not jobs:
        return 1

    saved = poll_and_download(jobs)
    log(f"DONE: {saved}/{len(todo)} video(s) saved to {OUTPUT_DIR}")
    return 0 if saved + (len(prompt_files) - len(todo)) == len(prompt_files) else 1


if __name__ == "__main__":
    sys.exit(main())
