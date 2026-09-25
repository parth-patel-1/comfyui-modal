"""MiniMax H3 video generation on the Modal-hosted ComfyUI server.

Reuses the proven ``workflows/minimax_h3_t2v_api.json`` graph (the same one
``make_video_api.py`` submits): patches the prompt, resolution, frame count,
step count, seed and fps, then submits through the shared ``ComfyUIClient``.
Also provides ``draft_video_prompt`` so the LLM can write a product-video
prompt from the shoot's product profile.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from . import prompts

VIDEO_TEMPLATE = Path(__file__).resolve().parent.parent / "workflows" / "minimax_h3_t2v_api.json"

# Node ids inside workflows/minimax_h3_t2v_api.json
PROMPT_NODE = "5"    # MiniMaxH3ImageToVideo (prompt / width / height / length)
NOISE_NODE = "6"     # RandomNoise (noise_seed)
STEPS_NODE = "9"     # BasicScheduler (steps)
VIDEO_NODE = "13"    # CreateVideo (fps)
SAVE_NODE = "14"     # SaveVideo (filename_prefix)

#: (width, height) presets known to work with the H3 template.
RESOLUTIONS = {
    "landscape 864x480": (864, 480),
    "portrait 480x864": (480, 864),
    "square 720x720": (720, 720),
}

#: frame-count presets at 24 fps.
FRAME_PRESETS = {
    "~2s (49 frames)": 49,
    "~3s (73 frames)": 73,
    "~4s (97 frames)": 97,
    "~5s (124 frames)": 124,
}


def load_template() -> dict:
    return json.loads(VIDEO_TEMPLATE.read_text(encoding="utf-8"))


def build_video_workflow(
    prompt: str,
    *,
    width: int = 864,
    height: int = 480,
    frames: int = 124,
    steps: int = 20,
    seed: int | None = None,
    fps: int = 24,
    filename_prefix: str = "video/ecom",
    start_image: str | None = None,
) -> dict:
    """Patch the MiniMax H3 API workflow with concrete parameters.

    ``seed=None`` (or a negative value) picks a random seed per call.
    ``start_image`` is a ComfyUI server file name (from upload_image) that
    becomes the clip's first frame (image-to-video).
    """
    wf = load_template()
    wf[PROMPT_NODE]["inputs"]["prompt"] = prompt
    wf[PROMPT_NODE]["inputs"]["width"] = int(width)
    wf[PROMPT_NODE]["inputs"]["height"] = int(height)
    wf[PROMPT_NODE]["inputs"]["length"] = int(frames)
    wf[NOISE_NODE]["inputs"]["noise_seed"] = (
        int(seed) if seed is not None and int(seed) >= 0 else random.randint(1, 2**31 - 1)
    )
    wf[STEPS_NODE]["inputs"]["steps"] = int(steps)
    wf[VIDEO_NODE]["inputs"]["fps"] = int(fps)
    wf[SAVE_NODE]["inputs"]["filename_prefix"] = filename_prefix
    if start_image:
        # MiniMaxH3ImageToVideo has an optional first_frame IMAGE input; wire a
        # LoadImage node to it so a generated/uploaded still becomes frame one.
        wf["16"] = {"class_type": "LoadImage", "inputs": {"image": start_image, "upload": "image"}}
        wf[PROMPT_NODE]["inputs"]["first_frame"] = ["16", 0]
    return wf


def generate_video(comfy, prompt: str, out_dir: str | Path, **kwargs) -> tuple[str, list[Path]]:
    """submit + wait + download the MP4; returns (prompt_id, saved files)."""
    wf = build_video_workflow(prompt, **kwargs)
    return comfy.generate(wf, SAVE_NODE, out_dir)


def draft_video_prompt(llm, product_profile: dict, shot_prompt: str = "") -> str:
    """Ask the LLM to write a MiniMax H3 prompt for this product."""
    data = llm.chat_json(
        task="video_prompt",
        system=prompts.VIDEO_PROMPT_SYSTEM,
        user=json.dumps({
            "product_profile": product_profile,
            "shot_prompt_to_adapt": shot_prompt,
        }),
    )
    return (data.get("prompt") or "").strip()