"""ComfyUI API-format workflow builders for GenStudio jobs.

Pure Python (no modal import) so the FastAPI backend can use it directly.
Templates live in modal_app/workflows/*.json.
"""

from __future__ import annotations

import json
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).parent / "workflows"


def _template(name: str) -> dict:
    return json.loads((WORKFLOWS_DIR / name).read_text())


def _snap_frames(duration_s: int, fps: int = 24) -> int:
    """MiniMax H3 frame grid: frame count must satisfy n % 17 == 5."""
    frames = max(5, int(round(duration_s * fps)))
    while frames % 17 != 5:
        frames += 1
    return frames


# ------------------------------------------------------------------ image

def build_image_t2i(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    steps: int = 25,
    cfg: float = 1.0,
) -> dict:
    wf = _template("qwen_image_2.1_api.json")
    wf["5"]["inputs"]["width"] = int(width)
    wf["5"]["inputs"]["height"] = int(height)
    wf["6"]["inputs"]["text"] = prompt
    wf["7"]["inputs"]["text"] = negative_prompt
    wf["8"]["inputs"].update(seed=int(seed), steps=int(steps), cfg=float(cfg))
    return wf


def build_image_edit(
    prompt: str,
    negative_prompt: str,
    reference_names: list[str],
    width: int,
    height: int,
    seed: int,
    steps: int = 25,
    cfg: float = 1.0,
) -> dict:
    """Multi-reference edit: one dynamic LoadImage node per reference,
    wired into TextEncodeQwenImage21 as images.image_1..N.

    reference_names: server-side ComfyUI input filenames (uploaded via
    /upload/image beforehand).
    """
    if not reference_names:
        raise ValueError("edit mode requires at least one reference image")
    wf = _template("qwen_image_2.1_edit_api.json")

    # template ships LoadImage nodes "1", "13", "14" -- rebuild them.
    for node_id in ("1", "13", "14"):
        wf.pop(node_id, None)
    encode = wf["6"]["inputs"]
    for key in [k for k in encode if k.startswith("images.")]:
        del encode[key]

    for i, name in enumerate(reference_names, start=1):
        node_id = str(100 + i)
        wf[node_id] = {
            "class_type": "LoadImage",
            "inputs": {"image": name},
        }
        encode[f"images.image_{i}"] = [node_id, 0]

    encode["prompt"] = prompt
    encode["negative_prompt"] = negative_prompt
    encode["resolution"] = int(max(width, height))
    wf["7"]["inputs"]["width"] = int(width)
    wf["7"]["inputs"]["height"] = int(height)
    wf["9"]["inputs"].update(seed=int(seed), steps=int(steps), cfg=float(cfg))
    return wf

# ------------------------------------------------------------------ video

def build_video_t2v(
    prompt: str,
    width: int,
    height: int,
    duration_s: int,
    seed: int,
    steps: int = 20,
    turbo: bool = False,
) -> dict:
    """Text-to-video with native audio. duration snaps to the 17k+5 grid."""
    wf = _template("minimax_h3_t2v_api.json")
    wf["5"]["inputs"]["prompt"] = prompt
    wf["5"]["inputs"]["width"] = int(width)
    wf["5"]["inputs"]["height"] = int(height)
    wf["5"]["inputs"]["length"] = _snap_frames(duration_s)
    wf["6"]["inputs"]["noise_seed"] = int(seed)
    if turbo:
        steps = min(steps, 8)
        wf["16"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["15", 0],
                "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
                "strength_model": 1.0,
            },
        }
        wf["15"]["inputs"]["model"] = ["16", 0]
    wf["9"]["inputs"]["steps"] = int(steps)
    return wf


def build_video_i2v(
    prompt: str,
    first_frame: str,
    last_frame: str | None,
    width: int,
    height: int,
    duration_s: int,
    seed: int,
    steps: int = 20,
    turbo: bool = False,
) -> dict:
    """Image-to-video: first_frame required, last_frame optional
    (MiniMaxH3ImageToVideo accepts optional first_frame/last_frame IMAGEs)."""
    wf = _template("minimax_h3_i2v_api.json")
    wf["16"]["inputs"]["image"] = first_frame
    node5 = wf["5"]["inputs"]
    node5["prompt"] = prompt
    node5["width"] = int(width)
    node5["height"] = int(height)
    node5["length"] = _snap_frames(duration_s)
    node5["first_frame"] = ["16", 0]
    if last_frame:
        wf["17"]["inputs"]["image"] = last_frame
        node5["last_frame"] = ["17", 0]
    else:
        wf.pop("17", None)
        node5.pop("last_frame", None)
    wf["6"]["inputs"]["noise_seed"] = int(seed)
    if turbo:
        steps = min(steps, 8)
        wf["18"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["15", 0],
                "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
                "strength_model": 1.0,
            },
        }
        wf["15"]["inputs"]["model"] = ["18", 0]
    wf["9"]["inputs"]["steps"] = int(steps)
    return wf