"""Minimal ComfyUI HTTP API client: upload / submit / poll / download.

Generalizes the pattern proven in ``make_video_api.py`` against the
Modal-hosted ComfyUI server (handles cold-start timeouts, node validation
errors, and SaveImage/SaveVideo output shapes).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger("ecom_app.comfyui")


class ComfyUIError(RuntimeError):
    pass


class ComfyUIClient:
    def __init__(self, base_url: str, *, poll_interval: int = 10, max_wait: int = 45 * 60):
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.max_wait = max_wait

    def probe(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/object_info", timeout=(30, 900))
            return r.status_code == 200
        except requests.RequestException:
            return False

    def upload_image(self, path: str | Path) -> str:
        """Upload a local image to the server's input folder; returns the
        server-side reference usable in a LoadImage node."""
        p = Path(path)
        with p.open("rb") as fh:
            resp = requests.post(
                f"{self.base_url}/upload/image",
                files={"image": (p.name, fh)},
                data={"overwrite": "true"},
                timeout=(30, 600),
            )
        if resp.status_code != 200:
            raise ComfyUIError(f"upload failed for {p}: {resp.status_code} {resp.text[:500]}")
        data = resp.json()
        name = data.get("name", p.name)
        sub = data.get("subfolder") or ""
        server_ref = f"{sub}/{name}" if sub else name
        logger.info("uploaded %s -> %s", p.name, server_ref)
        return server_ref

    def submit(self, workflow: dict) -> str:
        resp = requests.post(
            f"{self.base_url}/prompt",
            json={"prompt": workflow},
            timeout=(30, 30 * 60),  # cold container may take minutes to accept
        )
        if resp.status_code != 200:
            raise ComfyUIError(f"/prompt {resp.status_code}: {resp.text[:1000]}")
        payload = resp.json()
        if payload.get("node_errors"):
            raise ComfyUIError(f"workflow rejected: {payload['node_errors']}")
        return payload["prompt_id"]

    def wait(self, prompt_id: str) -> dict:
        deadline = time.time() + self.max_wait
        while time.time() < deadline:
            try:
                hist = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=60).json()
            except requests.RequestException as e:
                logger.warning("history poll failed (%s); retrying", e)
                time.sleep(self.poll_interval)
                continue
            entry = hist.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("completed") or status.get("status_str") in ("success", "error"):
                    if status.get("status_str") != "success":
                        raise ComfyUIError(f"prompt {prompt_id} failed: {status}")
                    return entry
            time.sleep(self.poll_interval)
        raise ComfyUIError(f"timed out waiting for prompt {prompt_id}")

    def download_images(self, entry: dict, save_node_id: str, dest_dir: str | Path) -> list[Path]:
        outputs = entry.get("outputs", {})
        node_out = outputs.get(str(save_node_id), {})
        files = (
            node_out.get("images")
            or node_out.get("gifs")
            or node_out.get("videos")
            or []
        )
        if not files:
            raise ComfyUIError(f"no files in outputs of node {save_node_id}: {list(outputs)}")
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        saved = []
        for f in files:
            params = {
                "filename": f["filename"],
                "subfolder": f.get("subfolder", ""),
                "type": f.get("type", "output"),
            }
            resp = requests.get(f"{self.base_url}/view", params=params, timeout=600)
            resp.raise_for_status()
            out = dest / f["filename"]
            out.write_bytes(resp.content)
            logger.info("downloaded %s (%.1f KB)", out.name, out.stat().st_size / 1024)
            saved.append(out)
        return saved

    def generate(self, workflow: dict, save_node_id: str, dest_dir: str | Path) -> tuple[str, list[Path]]:
        """submit + wait + download; returns (prompt_id, saved files)."""
        prompt_id = self.submit(workflow)
        entry = self.wait(prompt_id)
        return prompt_id, self.download_images(entry, save_node_id, dest_dir)
