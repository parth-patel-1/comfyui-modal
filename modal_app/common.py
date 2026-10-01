"""Shared infrastructure for the GenStudio Modal engine apps.

Config-driven so the backend admin panel can change GPU type, autoscaler
limits and scaledown window and re-run `modal deploy` without code edits.
Values come from modal_app/deploy_config.json (written by the backend
before deploying; never committed).

Both engine apps (image/video) share the same container image and model
volumes as the legacy comfyui_app.py, so model weights are downloaded once.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import modal

COMFYUI_DIR = "/root/comfy/ComfyUI"
COMFYUI_PORT = 8188
APP_DIR = Path(__file__).parent
DEPLOY_CONFIG_PATH = APP_DIR / "deploy_config.json"

ENGINE_TOKEN_SECRET = "genstudio-engine-token"

# Persistent volumes -- same names as the legacy comfyui_app.py so the
# downloaded weights are reused.
models_volume = modal.Volume.from_name("comfyui-models", create_if_missing=True)
outputs_volume = modal.Volume.from_name("comfyui-outputs", create_if_missing=True)
input_volume = modal.Volume.from_name("comfyui-input", create_if_missing=True)
user_volume = modal.Volume.from_name("comfyui-user", create_if_missing=True)

VOLUMES: dict[str, modal.Volume] = {
    f"{COMFYUI_DIR}/models": models_volume,
    f"{COMFYUI_DIR}/output": outputs_volume,
    f"{COMFYUI_DIR}/input": input_volume,
    f"{COMFYUI_DIR}/user": user_volume,
}

# Models auto-downloaded into the comfyui-models volume on first use.
# (subfolder under ComfyUI/models, URL) -- copied from comfyui_app.py.
MODEL_DOWNLOADS: list[tuple[str, str]] = [
    # Qwen-Image-2.1: one model for text-to-image AND instruction editing.
    (
        "diffusion_models",
        "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/diffusion_models/qwen_image_2.1_int8_convrot.safetensors",
    ),
    (
        "text_encoders",
        "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_bf16.safetensors",
    ),
    (
        "text_encoders",
        "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors",
    ),
    (
        "vae",
        "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors",
    ),
    # MiniMax H3: text-to-video + image-to-video (first/last frame) with
    # native stereo audio, 24 fps, 768-short-edge canvas.
    (
        "diffusion_models",
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    ),
    (
        "text_encoders",
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    ),
    (
        "vae",
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_int8_convrot.safetensors",
    ),
    (
        "vae",
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors",
    ),
    (
        "loras",
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
    ),
]

DEFAULT_CONFIG: dict = {
    "comfyui_version": "v0.37.0",
    "image": {
        "gpu": "L40S",
        "max_containers": 1,
        "min_containers": 0,
        "scaledown_window_s": 300,
        "max_inputs": 8,
        "startup_timeout_s": 1200,
    },
    "video": {
        "gpu": "L40S",
        "max_containers": 1,
        "min_containers": 0,
        "scaledown_window_s": 300,
        "max_inputs": 8,
        "startup_timeout_s": 1200,
    },
}

def load_engine_config(engine: str) -> dict:
    """Read deploy_config.json; engine section inherits top-level keys."""
    config = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if DEPLOY_CONFIG_PATH.exists():
        config.update(json.loads(DEPLOY_CONFIG_PATH.read_text()))
    merged = dict(config)
    merged.update(config.get(engine, {}))
    return merged


def build_image(comfyui_version: str) -> modal.Image:
    """ComfyUI container image (cached by Modal after first build)."""
    return (
        modal.Image.debian_slim(python_version="3.11")
        .apt_install("git")
        .run_commands(
            f"git clone --depth 1 --branch {comfyui_version} "
            f"https://github.com/Comfy-Org/ComfyUI.git {COMFYUI_DIR}"
        )
        .workdir(COMFYUI_DIR)
        .run_commands("python -m pip install -r requirements.txt")
        .pip_install("safetensors>=0.4")
        # proxy dependencies (bearer-token ASGI proxy in comfy_proxy.py)
        .pip_install("httpx>=0.27", "websockets>=13")
        .run_commands(
            f"find {COMFYUI_DIR}/models {COMFYUI_DIR}/input {COMFYUI_DIR}/output "
            f"-mindepth 1 -delete"
        )
    )


def _download_file(url: str, dest: Path, max_attempts: int = 3) -> None:
    """Stream url to dest atomically with resume support."""
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    part_file = dest.with_name(dest.name + ".part")

    for attempt in range(1, max_attempts + 1):
        try:
            resume_from = part_file.stat().st_size if part_file.exists() else 0
            headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
            with requests.get(url, stream=True, timeout=(30, 60), headers=headers) as r:
                if resume_from and r.status_code == 416:
                    part_file.unlink()
                    raise ValueError(f"stale .part file, restarting")
                if resume_from and r.status_code != 206:
                    resume_from = 0
                total = resume_from + int(r.headers.get("content-length", 0))
                done = resume_from
                last_report = resume_from
                mode = "ab" if resume_from else "wb"
                with open(part_file, mode) as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        done += len(chunk)
                        if done - last_report > 512 * 1024 * 1024 or done == total:
                            last_report = done
                            pct = f"{100 * done / total:.0f}%" if total else "?%"
                            print(f"  {dest.name}: {done / 1e9:.2f} GB ({pct})")
                if total and done != total:
                    raise ValueError(f"incomplete transfer ({done}/{total} bytes)")
            os.replace(part_file, dest)
            print(f"  {dest.name}: done.")
            return
        except Exception as e:
            print(f"  attempt {attempt}/{max_attempts} for {dest.name} failed: {e}")
            if attempt == max_attempts:
                raise RuntimeError(f"Could not download {url}") from e
            time.sleep(5 * attempt)


def ensure_models() -> bool:
    """Download missing models into the volume; True if anything downloaded."""
    models_dir = Path(COMFYUI_DIR) / "models"
    downloaded = False
    for subfolder, url in MODEL_DOWNLOADS:
        filename = url.split("/")[-1].split("?")[0]
        dest = models_dir / subfolder / filename
        if dest.exists():
            print(f"Model already present: {subfolder}/{filename}")
            continue
        print(f"Downloading {url}")
        print(f"  -> {dest}")
        _download_file(url, dest)
        downloaded = True
    return downloaded


def start_comfyui() -> None:
    """Launch ComfyUI in the background (Popen -- Modal's web wrappers check
    the port only after this function returns)."""
    if ensure_models():
        models_volume.commit()
    print(f"Starting ComfyUI on port {COMFYUI_PORT} ...")
    subprocess.Popen(
        [
            "python", "main.py",
            "--listen", "0.0.0.0",
            "--port", str(COMFYUI_PORT),
            "--disable-auto-launch",
        ],
        cwd=COMFYUI_DIR,
    )