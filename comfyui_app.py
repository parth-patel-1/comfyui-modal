"""
Host ComfyUI (https://github.com/Comfy-Org/ComfyUI) on Modal (https://modal.com)
and use it as a website in your browser.

Deploy as a persistent web app:

    modal deploy comfyui_app.py

    -> prints a URL like https://<your-workspace>--comfyui.modal.run

Pre-download the default models into the volume (optional -- this also happens
automatically on the first boot of the web app):

    modal run comfyui_app.py            # add --skip-models to skip

Stop the app when you are done (ends GPU billing):

    modal app stop comfyui-hosting

Full instructions: see README.md in this folder.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import modal

# ---------------------------------------------------------------------------
# Configuration -- edit these to taste
# ---------------------------------------------------------------------------

APP_NAME = "comfyui-hosting"

# ComfyUI release tag: https://github.com/Comfy-Org/ComfyUI/releases
COMFYUI_VERSION = "v0.37.0"

# Where ComfyUI lives inside the container image. Deliberately a plain string
# with forward slashes: this value is evaluated on YOUR machine too (image
# build commands and volume mount paths), where a Windows pathlib.Path would
# render as backslashes and break the Linux container.
COMFYUI_DIR = "/root/comfy/ComfyUI"

# Port ComfyUI listens on inside the container (Modal proxies it to the web).
COMFYUI_PORT = 8188

# GPU for the web app. Options (approx. $/hr -- always check modal.com/pricing):
#   "T4"       16 GB   ~$0.59/hr  (fine for SD1.5 / SDXL)
#   "L4"       24 GB   ~$0.80/hr
#   "A10G"     24 GB   ~$1.10/hr  (default; Qwen-Image-2.1 int8; also runs
#                                MiniMax H3 video via CPU offloading)
#   "L40S"     48 GB   ~$1.95/hr  (recommended for MiniMax H3 video / Flux dev)
#   "A100-80GB" 80 GB  ~$5.24/hr
#   "H100"     80 GB   ~$6.79/hr
GPU_CONFIG = "L40S"

# Seconds of inactivity before the GPU container scales down to zero.
# You are billed per second while a container is running.
SCALEDOWN_WINDOW_S = 5 * 60

# Max concurrent HTTP requests one container may serve. ComfyUI's browser UI
# fires many parallel requests (static assets, /api/object_info, a long-lived
# WebSocket, progress polling), so this must be generous: whenever MORE
# requests are in flight than this, Modal starts an additional GPU container.
MAX_INPUTS = 50

# Hard cap on concurrently running GPU containers. 1 means you never pay for a
# second GPU: extra requests queue at the proxy instead of scaling out. (Each
# extra container would be an independent ComfyUI with its own queue/history.)
MAX_CONTAINERS = 1

# How long Modal waits on a cold start for ComfyUI to accept requests.
# The first boot may download models, so keep this generous.
STARTUP_TIMEOUT_S = 20 * 60

# Models that are automatically downloaded into the `comfyui-models` volume
# on first use. Each entry: (ComfyUI models subfolder, download URL).
# Add/remove entries freely. Public (non-gated) Hugging Face URLs work best,
# e.g. https://huggingface.co/<org>/<repo>/resolve/main/<file>
MODEL_DOWNLOADS: list[tuple[str, str]] = [
    # Qwen-Image-2.1 (https://huggingface.co/Qwen/Qwen-Image-2.1) -- ONE model for
    # BOTH text-to-image and instruction-based image editing; native 2K output,
    # crisp text rendering, alpha/transparent backgrounds.
    # Files are the official ComfyUI packaging (Comfy-Org/Qwen-Image-2.1) and
    # match the "Qwen-Image-2.1" workflow templates shipped with ComfyUI v0.37.0
    # (Template Library -> search "Qwen-Image-2.1"; defaults: 25 steps, cfg 1,
    # euler + simple scheduler). Total ~24 GB -- fits a 24 GB GPU (A10G) because
    # ComfyUI offloads the text encoder to RAM after encoding the prompt.
    # (An extra ~8.7 GB int8 copy of the text encoder is included below as a
    # smaller-VRAM alternative for workflows.)
    (
        "diffusion_models",
        # int8-quantized diffusion model (~6.8 GB) -- the templates' default,
        # fast and low-VRAM. (Full-precision bf16 is under optional extras.)
        "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/diffusion_models/qwen_image_2.1_int8_convrot.safetensors",
    ),
    (
        "text_encoders",
        # Qwen3-VL 8B text encoder, bf16 (~16.3 GB) -- the templates' default.
        "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_bf16.safetensors",
    ),
    (
        "text_encoders",
        # Same encoder, int8-quantized (~8.7 GB) -- smaller disk/RAM footprint;
        # the "Qwen-Image-2.1 int8" workflow templates point at this one.
        "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors",
    ),
    (
        "vae",
        # Qwen-Image-2.1 VAE (~0.6 GB) -- 4-channel, supports transparency.
        "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors",
    ),
    # --- MiniMax H3 text-to-video -------------------------------------------
    # MiniMax H3 is an omni-modal video model: text-to-video with NATIVE stereo
    # audio (dialogue / SFX / music in one pass), 24 fps, up to ~15 s, on a
    # 768px-short-edge canvas (<=768x1344). These are the official ComfyUI
    # packaging of the weights (https://huggingface.co/Comfy-Org/MiniMax-H3) and
    # match the "MiniMax H3: Text to Video" workflow template (Template Library
    # -> Video -> MiniMax H3); ready-made copies live in workflows/. ~42 GB total.
    # A 24 GB A10G works (ComfyUI offloads the 15.7 GB text encoder after
    # encoding); for faster generation use a 48 GB GPU (GPU_CONFIG = "L40S").
    (
        "diffusion_models",
        # int8-quantized, pruned fl2va diffusion model (~21.0 GB)
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    ),
    (
        "text_encoders",
        # Qwen3-VL 32B text encoder for H3, nvfp4 AWQ quant (~15.7 GB) -- the
        # template default; runs on any GPU (unlike the fp4 Blackwell variant)
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    ),
    (
        "vae",
        # H3 video VAE, int8 (~2.8 GB) -- decodes the video stream
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_int8_convrot.safetensors",
    ),
    (
        "vae",
        # H3 audio VAE, fp32 (~0.6 GB) -- decodes the stereo audio stream
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors",
    ),
    (
        "loras",
        # turbo LoRA (~2.0 GB) -- enables the workflow's "Turbo mode" toggle:
        # 8 steps instead of 20 (~2.5x faster, slight quality trade-off)
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
    ),
    # --- optional extras: uncomment what you want ---------------------------
    # Full-precision (bf16) Qwen-Image-2.1 diffusion model (~13.3 GB, slightly
    # better quality, more VRAM -- best on a 48 GB GPU like L40S):
    # (
    #     "diffusion_models",
    #     "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/diffusion_models/qwen_image_2.1_bf16.safetensors",
    # ),
    # MiniMax H3 reference-to-video (r2v) diffusion model, int8 pruned (~21 GB)
    # -- for the "MiniMax H3: Reference to Video" template:
    # (
    #     "diffusion_models",
    #     "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    # ),
    # Stable Diffusion XL base (~6.9 GB):
    # (
    #     "checkpoints",
    #     "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
    # ),
]

# ---------------------------------------------------------------------------
# Modal resources: volumes, app, image
# ---------------------------------------------------------------------------

# Persistent storage (survives container scale-down, redeploys and app stops):
#   comfyui-models  -> model weights (re-launch never re-downloads these)
#   comfyui-outputs -> generated images
#   comfyui-input   -> images you upload for img2img / ControlNet
#   comfyui-user    -> saved workflows, browser settings, etc.
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

app = modal.App(APP_NAME)

# Container image: Debian slim + Python 3.11 + ComfyUI at a pinned release.
# The build takes a few minutes the first time and is cached by Modal after.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .run_commands(
        f"git clone --depth 1 --branch {COMFYUI_VERSION} "
        f"https://github.com/Comfy-Org/ComfyUI.git {COMFYUI_DIR}"
    )
    .workdir(COMFYUI_DIR)
    .run_commands("python -m pip install -r requirements.txt")
    # safetensors is required to load every model weight used here (all
    # downloads above are .safetensors); ComfyUI's own requirements already pin
    # it - pinned here too so the dependency is explicit for this deployment.
    .pip_install("safetensors>=0.4")
    # ComfyUI ships placeholder files inside models/, input/ and output/
    # (e.g. models/checkpoints/put_checkpoints_here, input/example.png). Modal
    # refuses to mount a volume on a non-empty path, so empty those directories
    # here -- the comfyui-* volumes provide the real content at runtime.
    .run_commands(
        f"find {COMFYUI_DIR}/models {COMFYUI_DIR}/input {COMFYUI_DIR}/output "
        f"-mindepth 1 -delete"
    )
    # Add custom nodes at build time, e.g.:
    # .run_commands(
    #     "git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Manager.git "
    #     f"{COMFYUI_DIR}/custom_nodes/ComfyUI-Manager"
    # )
)

# ---------------------------------------------------------------------------
# Model download helpers (run inside Modal containers)
# ---------------------------------------------------------------------------


def _download_file(url: str, dest: Path, max_attempts: int = 3) -> None:
    """Stream `url` to `dest` atomically (via a .part file), with retries.

    If a previous attempt died mid-download, resumes from the existing .part
    file via an HTTP Range request instead of restarting multi-GB files.
    """
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    part_file = dest.with_name(dest.name + ".part")

    for attempt in range(1, max_attempts + 1):
        try:
            resume_from = part_file.stat().st_size if part_file.exists() else 0
            headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
            with requests.get(url, stream=True, timeout=(30, 60), headers=headers) as r:
                if resume_from and r.status_code == 416:
                    # Range past EOF: the .part is junk (e.g. left over from a
                    # different file) -- discard it and start over.
                    part_file.unlink()
                    raise ValueError(f"stale .part file ({resume_from} bytes), restarting")
                if resume_from and r.status_code != 206:
                    # Server ignored the Range header -- download from scratch.
                    resume_from = 0
                if resume_from:
                    served_from = r.headers.get("content-range", f"bytes {resume_from}-")
                    if not served_from.startswith(f"bytes {resume_from}-"):
                        part_file.unlink()
                        raise ValueError(f"unexpected content-range {served_from!r}")
                    print(f"  {dest.name}: resuming from {resume_from / 1e9:.2f} GB")
                total = resume_from + int(r.headers.get("content-length", 0))
                done = resume_from
                last_report = resume_from
                with open(part_file, "ab" if resume_from else "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        done += len(chunk)
                        if done - last_report > 512 * 1024 * 1024 or done == total:
                            last_report = done
                            pct = f"{100 * done / total:.0f}%" if total else "?%"
                            print(f"  {dest.name}: {done / 1e9:.2f} GB ({pct})")
                if total and done != total:
                    # Keep the .part file -- the retry below resumes from it.
                    raise ValueError(f"incomplete transfer ({done}/{total} bytes)")
            os.replace(part_file, dest)  # atomic: no half-written files
            print(f"  {dest.name}: done.")
            return
        except Exception as e:
            print(f"  attempt {attempt}/{max_attempts} for {dest.name} failed: {e}")
            if attempt == max_attempts:
                raise RuntimeError(
                    f"Could not download {url}. If this is a Hugging Face URL, "
                    "make sure the repo is public (not gated) and the URL is correct."
                ) from e
            time.sleep(5 * attempt)


def ensure_models() -> bool:
    """Download any missing models from MODEL_DOWNLOADS into the volume.

    Returns True if anything was downloaded (so callers can commit the volume).
    """
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


# ---------------------------------------------------------------------------
# Modal functions
# ---------------------------------------------------------------------------


@app.function(
    image=image,
    volumes=VOLUMES,
    timeout=60 * 60,  # allow long downloads
)
def download_models() -> None:
    """Idempotently download all models in MODEL_DOWNLOADS into the volume."""
    if ensure_models():
        models_volume.commit()
        print("Model volume committed.")
    else:
        print("All models already present -- nothing to do.")


@app.function(
    image=image,
    gpu=GPU_CONFIG,
    volumes=VOLUMES,
    timeout=60 * 60,  # hard limit for one interactive session on one container
    scaledown_window=SCALEDOWN_WINDOW_S,
    max_containers=MAX_CONTAINERS,  # never scale out to a second billed GPU
)
@modal.concurrent(max_inputs=MAX_INPUTS)  # keep high: each extra in-flight request past this would start a new GPU container
@modal.web_server(
    port=COMFYUI_PORT,
    startup_timeout=STARTUP_TIMEOUT_S,
    label="comfyui",  # final URL: https://<workspace>--comfyui.modal.run
)
def run_comfyui() -> None:
    """Serve the full ComfyUI web UI (and its HTTP API) from a GPU container."""
    # Self-healing: on the very first boot the volume is empty, so make sure
    # the default models are there before serving traffic.
    if ensure_models():
        models_volume.commit()

    # NOTE: must be Popen, NOT run -- Modal's @modal.web_server wrapper calls
    # this function synchronously and only checks whether the port is open
    # AFTER the function returns. A blocking subprocess.run would keep the
    # container permanently "not ready" (requests queue up as Pending).
    print(f"Starting ComfyUI v{COMFYUI_VERSION} on port {COMFYUI_PORT} ...")
    subprocess.Popen(
        [
            "python", "main.py",
            "--listen", "0.0.0.0",
            "--port", str(COMFYUI_PORT),
            "--disable-auto-launch",
        ],
        cwd=COMFYUI_DIR,
    )


@app.local_entrypoint()
def main(skip_models: bool = False) -> None:
    """Pre-download models into the `comfyui-models` volume.

    Run with: modal run comfyui_app.py   (add --skip-models to skip)
    """
    if skip_models:
        print("Skipping model download (--skip-models).")
    else:
        start = time.time()
        download_models.remote()
        print(f"Models ready (took {time.time() - start:.0f}s).")
    print("Next step: `modal deploy comfyui_app.py` to publish the web app.")

