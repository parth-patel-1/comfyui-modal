"""GenStudio image engine: Qwen-Image-2.1 (t2i + multi-reference edit).

Deploy with:
    modal deploy modal_app/image_app.py

GPU type / autoscaler limits are read from modal_app/deploy_config.json
(written by the backend admin panel before deploying).
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

config = load_engine_config("image")
image = build_image(config["comfyui_version"]).add_local_python_source(
    "common", "comfy_proxy"
)

app = modal.App("genstudio-image")


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
@modal.asgi_app(label="genstudio-image")
def serve() -> ComfyProxy:
    """Start ComfyUI, then serve it through the bearer-token proxy."""
    start_comfyui()
    return ComfyProxy()
