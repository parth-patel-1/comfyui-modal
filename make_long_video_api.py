"""Generate LONG MiniMax H3 videos via the deployed ComfyUI HTTP API on Modal.

The "infinite length" trick
---------------------------
MiniMax H3 generates one clip of ~124-362 frames (~5-15 s at 24 fps) per pass.
The trick to get (practically) unlimited duration is LAST-FRAME -> FIRST-FRAME
CHAINING, all inside a single ComfyUI graph:

    segment 1: text -> video (124 frames) --VAEDecode--> frames
                                                     +- ImageFromBatch(index = frames-1) -> last frame
    segment 2: MiniMaxH3ImageToVideo(first_frame = last frame of segment 1) -> 124 new frames
    segment 3: ... first_frame = last frame of segment 2 ...
    ...
    ImageBatch x N-1   -> one long image batch   --CreateVideo--> SaveVideo (one MP4)
    AudioConcat x N-1  -> one long audio track --/

Because every segment is conditioned on the exact last frame of the previous
one, motion/scene continues seamlessly and you can chain as many segments as
your time budget allows (each 124-frame segment costs roughly one normal
generation). The whole chain runs end-to-end as ONE /prompt submission.

This script builds that chained API workflow for ANY number of segments,
submits it to the Modal-hosted ComfyUI server, polls /history until done,
and downloads the finished MP4 into output/.

Usage:
    # 4 segments (~20 s) with one prompt reused for every segment:
    python make_long_video_api.py --prompt "a sailboat crossing a calm sea at sunrise" --segments 4

    # Different prompt per segment (shot-by-shot story), from a JSON file:
    python make_long_video_api.py --prompts-json my_segments.json
    #   my_segments.json = ["shot 1 ...", "shot 2 ...", "shot 3 ..."]

    # Just write the workflow JSON (e.g. to inspect or POST manually):
    python make_long_video_api.py --segments 4 --prompt "..." --dump workflows/minimax_h3_long_video_api.json

    # Longer segments (up to ~362 frames / ~15 s each -- model's trained max):
    python make_long_video_api.py --prompt "..." --segments 3 --frames 362
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://patelparth268268--comfyui.modal.run"
OUTPUT_DIR = Path(__file__).parent / "output"

FPS = 24
# MiniMaxH3ImageToVideo snaps length to a 17k+5 grid; 124 = ~5 s (default),
# 362 = ~15 s is the top of the model's trained range.
MIN_FRAMES = 5
MAX_FRAMES = 3600
TRAINED_MAX_FRAMES = 362

# MiniMax H3 model files (same as workflows/minimax_h3_t2v_api.json).
UNET_NAME = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
CLIP_NAME = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE_NAME = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO_VAE_NAME = "minimax_h3_audio_vae_fp32.safetensors"

SAVE_NODE_ID = "701"  # SaveVideo node id emitted by build_long_video_workflow()

POLL_INTERVAL_S = 15
MAX_WAIT_S = 60 * 60  # one Modal container hard limit is 1 h per request

# --------------------------------------------------------------------------- #
# Workflow builder                                                             #
# --------------------------------------------------------------------------- #
def build_long_video_workflow(
    prompts: list[str],
    width: int = 864,
    height: int = 480,
    frames: int = 124,
    steps: int = 20,
    seed: int = 42,
    filename_prefix: str = "video/MiniMax_H3_long",
) -> dict:
    """Build an API-format workflow that chains `len(prompts)` MiniMax H3
    segments via last-frame -> first-frame conditioning and stitches them into
    a single MP4 (video via ImageBatch, audio via core AudioConcat).

    Node id scheme (all ids are strings, as required by the /prompt API):
      shared loaders / samplers : "1"-"6", "15"
      segment i (0-based)       : (i+1)*100 + offset
            +1 MiniMaxH3ImageToVideo  +2 RandomNoise  +3 BasicGuider
            +4 SamplerCustomAdvanced  +5 VAEDecode    +6 VAEDecodeAudio
            +7 ImageFromBatch (last frame of this segment)
      image concat chain        : "501"...
      audio concat chain        : "601"...
      final mux                 : "700" CreateVideo, "701" SaveVideo
    """
    n = len(prompts)
    if n < 1:
        raise ValueError("need at least one segment prompt")
    if not (MIN_FRAMES <= frames <= MAX_FRAMES):
        raise ValueError(f"frames must be in [{MIN_FRAMES}, {MAX_FRAMES}]")

    wf: dict = {
        # --- shared loaders --------------------------------------------------
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": UNET_NAME, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP_NAME, "type": "minimax"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE_NAME}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE_NAME}},
        # --- shared sampling config ------------------------------------------
        "5": {"class_type": "KSamplerSelect",
              "inputs": {"sampler_name": "res_multistep"}},
        "6": {"class_type": "BasicScheduler",
              "inputs": {"model": ["15", 0], "steps": steps,
                         "scheduler": "simple", "denoise": 1.0}},
        # MiniMaxH3SigmaShift is REQUIRED (audio-aware sampling schedule).
        "15": {"class_type": "MiniMaxH3SigmaShift",
               "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
    }

    decode_ids: list[str] = []  # VAEDecode node ids, one per segment
    audio_ids: list[str] = []   # VAEDecodeAudio node ids, one per segment

    for i, prompt in enumerate(prompts):
        base = (i + 1) * 100
        mm_inputs: dict = {
            "clip": ["2", 0],
            "vae": ["3", 0],
            "prompt": prompt,
            "width": width,
            "height": height,
            "length": frames,
        }
        if i > 0:
            # THE TRICK: condition this segment on the previous segment's
            # final decoded frame -> seamless continuation.
            mm_inputs["first_frame"] = [str(base - 100 + 7), 0]
        wf[str(base + 1)] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": mm_inputs}
        wf[str(base + 2)] = {"class_type": "RandomNoise",
                             "inputs": {"noise_seed": seed + i,
                                        "control_after_generate": "fixed"}}
        wf[str(base + 3)] = {"class_type": "BasicGuider",
                             "inputs": {"model": ["15", 0],
                                        "conditioning": [str(base + 1), 0]}}
        wf[str(base + 4)] = {"class_type": "SamplerCustomAdvanced",
                             "inputs": {"noise": [str(base + 2), 0],
                                        "guider": [str(base + 3), 0],
                                        "sampler": ["5", 0],
                                        "sigmas": ["6", 0],
                                        "latent_image": [str(base + 1), 1]}}
        wf[str(base + 5)] = {"class_type": "VAEDecode",
                             "inputs": {"samples": [str(base + 4), 0], "vae": ["3", 0]}}
        wf[str(base + 6)] = {"class_type": "VAEDecodeAudio",
                             "inputs": {"samples": [str(base + 4), 0], "vae": ["4", 0]}}
        wf[str(base + 7)] = {"class_type": "ImageFromBatch",
                             "inputs": {"image": [str(base + 5), 0],
                                        "batch_index": -1,  # LAST frame (negative = from end)
                                        "length": 1}}
        decode_ids.append(str(base + 5))
        audio_ids.append(str(base + 6))

    # --- stitch video: ImageBatch left-fold over all segments -----------------
    cur_img = [decode_ids[0], 0]
    for k in range(1, n):
        nid = str(500 + k)
        wf[nid] = {"class_type": "ImageBatch",
                   "inputs": {"image1": cur_img, "image2": [decode_ids[k], 0]}}
        cur_img = [nid, 0]

    # --- stitch audio: AudioConcat left-fold (core node, v0.37.0) -------------
    cur_aud = [audio_ids[0], 0]
    for k in range(1, n):
        nid = str(600 + k)
        wf[nid] = {"class_type": "AudioConcat",
                   "inputs": {"audio1": cur_aud, "audio2": [audio_ids[k], 0],
                              "direction": "after"}}
        cur_aud = [nid, 0]

    # --- mux + save one long MP4 ----------------------------------------------
    wf["700"] = {"class_type": "CreateVideo",
                 "inputs": {"images": cur_img, "audio": cur_aud,
                            "fps": FPS, "bit_depth": 8}}
    wf[SAVE_NODE_ID] = {"class_type": "SaveVideo",
                        "inputs": {"video": ["700", 0],
                                   "filename_prefix": filename_prefix,
                                   "format": "auto", "codec": "auto"}}
    return wf


def validate_workflow(wf: dict) -> None:
    """Cheap offline sanity check: every link must point at a node that exists
    and every class_type must be one the chained workflow is built from."""
    known_classes = {
        "UNETLoader", "CLIPLoader", "VAELoader", "KSamplerSelect",
        "BasicScheduler", "MiniMaxH3SigmaShift", "MiniMaxH3ImageToVideo",
        "RandomNoise", "BasicGuider", "SamplerCustomAdvanced", "VAEDecode",
        "VAEDecodeAudio", "ImageFromBatch", "ImageBatch", "AudioConcat",
        "CreateVideo", "SaveVideo",
    }
    errors = []
    for nid, node in wf.items():
        ct = node.get("class_type")
        if ct not in known_classes:
            errors.append(f"node {nid}: unknown class_type {ct!r}")
        for key, val in node.get("inputs", {}).items():
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str):
                if val[0] not in wf:
                    errors.append(f"node {nid} input {key}: link to missing node {val[0]}")
    if errors:
        raise ValueError("workflow failed validation:\n  " + "\n  ".join(errors))


# --------------------------------------------------------------------------- #
# API driver (same pattern as make_video_api.py)                               #
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def submit_and_download(workflow: dict, base_url: str) -> int:
    # --- submit ---------------------------------------------------------------
    log(f"POST {base_url}/prompt ... ({len(workflow)} nodes)")
    resp = requests.post(
        f"{base_url}/prompt",
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

    # --- poll history ----------------------------------------------------------
    deadline = time.time() + MAX_WAIT_S
    while time.time() < deadline:
        try:
            hist = requests.get(f"{base_url}/history/{prompt_id}", timeout=60).json()
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
                    vid = requests.get(f"{base_url}/view", params=params, timeout=600)
                    vid.raise_for_status()
                    dest = OUTPUT_DIR / f["filename"]
                    dest.write_bytes(vid.content)
                    log(f"Saved {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
                log("DONE")
                return 0
        else:
            try:
                q = requests.get(f"{base_url}/queue", timeout=30).json()
                running = len(q.get("queue_running", []))
                pending = len(q.get("queue_pending", []))
                log(f"still running... (running={running} pending={pending})")
            except requests.RequestException:
                log("still running... (queue probe failed)")
        time.sleep(POLL_INTERVAL_S)
    log("ERROR: timed out waiting for the prompt to finish")
    return 1


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
DEMO_PROMPTS = [
    "A red paper boat floats in a rain puddle on a quiet street at dawn, "
    "soft ripples, gentle rain. Audio: light rain patter, distant birds.",

    "The red paper boat drifts toward the curb, rain easing off, the first "
    "sunbeams hitting the puddle. Audio: rain fading, a single sparrow chirping.",

    "The red paper boat slips into the gutter stream, carried past fallen "
    "leaves in golden morning light. Audio: trickling water, a city waking up.",

    "The red paper boat sails out into a wide sunlit creek, sparkling water, "
    "camera slowly rising to reveal a park. Audio: flowing water, warm birdsong.",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Long MiniMax H3 video via last-frame->first-frame chaining.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--prompt", action="append",
                   help="Segment prompt. Repeat to give one prompt per segment; "
                        "combined with --segments it is cycled to fill.")
    p.add_argument("--prompts-json", type=Path,
                   help="Path to a JSON file containing a list of segment prompts "
                        "(one per segment, in order).")
    p.add_argument("--segments", type=int, default=4,
                   help="Number of chained segments (default: 4; used with --prompt)")
    p.add_argument("--frames", type=int, default=124,
                   help=f"Frames per segment at {FPS} fps, 17k+5 grid "
                        f"(default: 124 = ~5 s; trained max {TRAINED_MAX_FRAMES} = ~15 s)")
    p.add_argument("--width", type=int, default=864)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--seed", type=int, default=42,
                   help="Seed of segment 1; segment i uses seed+i")
    p.add_argument("--base-url", default=BASE_URL)
    p.add_argument("--filename-prefix", default="video/MiniMax_H3_long")
    p.add_argument("--dump", type=Path,
                   help="Only write the built workflow JSON here and exit "
                        "(no submission).")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # --- resolve the per-segment prompt list -----------------------------------
    if args.prompts_json:
        prompts = json.loads(args.prompts_json.read_text(encoding="utf-8"))
        if not isinstance(prompts, list) or not all(isinstance(x, str) for x in prompts):
            log("ERROR: --prompts-json must be a JSON list of strings")
            return 1
    elif args.prompt:
        # cycle the given prompt(s) to fill --segments
        prompts = [args.prompt[i % len(args.prompt)] for i in range(args.segments)]
    else:
        prompts = DEMO_PROMPTS[: max(1, args.segments)]
        log(f"No prompt given -- using {len(prompts)} built-in demo prompts.")

    n = len(prompts)
    secs = n * args.frames / FPS
    log(f"Plan: {n} chained segments x {args.frames} frames = ~{secs:.0f}s of video "
        f"at {FPS} fps ({args.width}x{args.height}, {args.steps} steps/segment)")
    if args.frames > TRAINED_MAX_FRAMES:
        log(f"WARNING: {args.frames} frames is beyond the model's trained range "
            f"({TRAINED_MAX_FRAMES}); quality may degrade.")

    workflow = build_long_video_workflow(
        prompts,
        width=args.width,
        height=args.height,
        frames=args.frames,
        steps=args.steps,
        seed=args.seed,
        filename_prefix=args.filename_prefix,
    )
    validate_workflow(workflow)
    log(f"Workflow built and validated ({len(workflow)} nodes).")

    if args.dump:
        args.dump.parent.mkdir(parents=True, exist_ok=True)
        args.dump.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        log(f"Workflow written to {args.dump} (--dump: not submitting)")
        return 0

    return submit_and_download(workflow, args.base_url)


if __name__ == "__main__":
    sys.exit(main())

