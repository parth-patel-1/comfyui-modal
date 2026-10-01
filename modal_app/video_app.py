"""GenStudio video engine: MiniMax H3 (t2v + i2v with first/last frame).

Deploy with:
    modal deploy modal_app/video_app.py

Deliberately a separate Modal app from the image engine so the two GPU
pools scale (and can be sized) independently.
"""

from __future__ import annotations

import modal

from common import (
    ENGINE_TOKEN_SECRET,
    VOLUMES,
    build_image,
    load_engine_config,
    start_comfyui,
)
from comfy_proxy import ComfyProxy

config = load_engine_config("video")
image = build_image(config["comfyui_version"]).add_local_python_source(
    "common", "comfy_proxy"
)

app = modal.App("genstudio-video")


@app.function(
    image=image,
    gpu=config["gpu"],
    volumes=VOLUMES,
    secrets=[modal.Secret.from_name(ENGINE_TOKEN_SECRET)],
    timeout=60 * 60,
    scaledown_window=config["scaledown_window_s"],
    min_containers=config["min_containers"],
    max_containers=config["max_containers"],
)
@modal.concurrent(max_inputs=config["max_inputs"])
@modal.asgi_app(label="genstudio-video")
def serve() -> ComfyProxy:
    """Start ComfyUI, then serve it through the bearer-token proxy."""
    start_comfyui()
    return ComfyProxy()
