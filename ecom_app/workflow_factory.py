"""Builds ComfyUI API workflow dicts from the repo's JSON templates.

Two engines:
- ``qwen_image_2.1_edit_api.json`` — image-to-image editing with 1-3 reference
  images (TextEncodeQwenImage21): raw product photo -> premium shot, and
  persona + product multi-reference shots.
- ``qwen_image_2.1_api.json`` — pure text-to-image: persona/background creation.

Only whitelisted fields are patched (prompts, seeds, sizes, file names); the
model wiring stays exactly as validated on the server.
"""

from __future__ import annotations

import json
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"
EDIT_TEMPLATE = WORKFLOWS_DIR / "qwen_image_2.1_edit_api.json"
T2I_TEMPLATE = WORKFLOWS_DIR / "qwen_image_2.1_api.json"

EDIT_SAVE_NODE = "11"
T2I_SAVE_NODE = "10"

# LoadImage node id -> TextEncodeQwenImage21 input key, in reference order:
# image_1 = product photo, image_2 = persona (optional), image_3 = spare.
_EDIT_LOAD_NODES = [
    ("1", "images.image_1"),
    ("13", "images.image_2"),
    ("14", "images.image_3"),
]


def _load_template(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_edit_workflow(
    *,
    prompt: str,
    negative_prompt: str,
    reference_images: list[str],
    seed: int,
    filename_prefix: str,
    resolution: int = 1024,
) -> dict:
    """image-to-image product shot.

    ``reference_images`` are ComfyUI server file names (from /upload/image),
    ordered: product first, persona second. Unused reference slots are removed
    from the graph so the encoder never sees duplicate/placeholder inputs.
    """
    if not 1 <= len(reference_images) <= 3:
        raise ValueError("edit workflow needs 1-3 reference images")
    wf = _load_template(EDIT_TEMPLATE)
    enc = wf["6"]["inputs"]
    padded = list(reference_images) + [None] * (3 - len(reference_images))
    for (node_id, input_key), server_name in zip(_EDIT_LOAD_NODES, padded):
        if server_name is None:
            wf.pop(node_id, None)
            enc.pop(input_key, None)
        else:
            wf[node_id]["inputs"]["image"] = server_name
    enc["prompt"] = prompt
    enc["negative_prompt"] = negative_prompt
    enc["resolution"] = resolution
    wf["9"]["inputs"]["seed"] = seed
    wf["11"]["inputs"]["filename_prefix"] = filename_prefix
    return wf


def build_t2i_workflow(
    *,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    filename_prefix: str,
) -> dict:
    wf = _load_template(T2I_TEMPLATE)
    wf["6"]["inputs"]["text"] = prompt
    wf["7"]["inputs"]["text"] = negative_prompt
    wf["5"]["inputs"]["width"] = width
    wf["5"]["inputs"]["height"] = height
    wf["8"]["inputs"]["seed"] = seed
    wf["10"]["inputs"]["filename_prefix"] = filename_prefix
    return wf
