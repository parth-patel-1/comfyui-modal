"""Smoke test for the model-download helpers in comfyui_app.py.

Downloads a small real file from Hugging Face into a temp directory,
verifying the streaming / redirect / atomic-rename logic that runs inside
Modal containers. Does NOT need Modal credentials.

Run from the project folder:

    .venv\\Scripts\\python test_download_helper.py      (Windows)
    .venv/bin/python test_download_helper.py           (macOS/Linux)
"""

import tempfile
from pathlib import Path

import comfyui_app

# Redirect the ComfyUI dir + download list to a small, real HF file
# (the repo README, a few hundred bytes, served via the same redirect
# mechanism as the big .safetensors model files).
tmp = Path(tempfile.mkdtemp(prefix="comfyui_smoke_"))
comfyui_app.COMFYUI_DIR = tmp
comfyui_app.MODEL_DOWNLOADS = [
    (
        "checkpoints",
        "https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/README.md",
    )
]

assert comfyui_app.ensure_models() is True, "expected a download to happen"
downloaded = tmp / "models" / "checkpoints" / "README.md"
assert downloaded.exists(), f"{downloaded} missing"
assert downloaded.stat().st_size > 100, "downloaded file looks empty/truncated"
assert not downloaded.with_name("README.md.part").exists(), ".part file left behind"

# Idempotency: a second run must not re-download anything.
assert comfyui_app.ensure_models() is False, "second run should download nothing"

print("OK: download helper works (redirects, streaming, atomic rename, idempotency).")
print(f"    test dir: {tmp}")
