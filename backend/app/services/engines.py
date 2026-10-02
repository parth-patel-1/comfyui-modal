"""ComfyUI engine HTTP client (bearer-token authenticated)."""

from __future__ import annotations

import logging
import time

import httpx

from app.core.config import get_settings

log = logging.getLogger("genstudio.engine")


class EngineError(RuntimeError):
    pass


class EngineClient:
    """Sync client for one Modal engine (image or video)."""

    def __init__(self, base_url: str, token: str | None = None,
                 poll_interval: float = 5.0, max_wait: float = 1200.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.max_wait = max_wait
        s = get_settings()
        self._headers = {"Authorization": f"Bearer {token or s.engine_bearer_token}"}

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, headers=self._headers,
                            timeout=httpx.Timeout(60.0, read=1800.0))

    def _cold_start_deadline(self, cold_start_wait: float | None = None) -> float:
        wait = cold_start_wait if cold_start_wait is not None \
            else get_settings().cold_start_wait_s
        return time.monotonic() + wait

    def wait_ready(self, cold_start_wait: float | None = None,
                   poll_every: float = 10.0) -> None:
        """Block until the engine answers /health with 200.

        Wakes a cold (scaled-to-zero) Modal container instead of failing the
        job. Raises EngineError only if still not ready after the deadline.
        """
        deadline = self._cold_start_deadline(cold_start_wait)
        waited = False
        while True:
            try:
                with self._client() as client:
                    resp = client.get("/health")
                if resp.status_code == 200:
                    if waited:
                        log.info("engine %s is warm", self.base_url)
                    return
            except httpx.HTTPError:
                pass  # connection errors count as "still cold"
            if time.monotonic() >= deadline:
                raise EngineError(
                    f"engine {self.base_url} not ready after cold-start wait")
            waited = True
            log.info("engine cold, waiting for startup (%.0fs remaining) ...",
                     deadline - time.monotonic())
            time.sleep(poll_every)

    def upload_image(self, data: bytes, name: str,
                     cold_start_wait: float | None = None) -> str:
        """Upload reference bytes to the engine input folder; returns the
        server-side name for LoadImage nodes. Retries while the engine is
        cold (503 'comfyui not ready') instead of failing the job."""
        deadline = self._cold_start_deadline(cold_start_wait)
        while True:
            with self._client() as client:
                resp = client.post(
                    "/upload/image",
                    files={"image": (name, data)},
                    data={"overwrite": "true"},
                )
            if resp.status_code == 200:
                payload = resp.json()
                sub = payload.get("subfolder") or ""
                return f"{sub}/{payload.get('name', name)}" if sub else payload.get("name", name)
            if resp.status_code == 503 and time.monotonic() < deadline:
                log.info("upload: engine cold, retrying in 10s ...")
                time.sleep(10.0)
                continue
            raise EngineError(f"upload failed: {resp.status_code} {resp.text[:300]}")

    def submit(self, workflow: dict, cold_start_wait: float | None = None) -> str:
        """Submit, retrying while the engine is cold (503 'not ready')."""
        deadline = self._cold_start_deadline(cold_start_wait)
        while True:
            with self._client() as client:
                resp = client.post("/prompt", json={"prompt": workflow})
            if resp.status_code == 200:
                payload = resp.json()
                if payload.get("node_errors"):
                    raise EngineError(f"workflow rejected: {payload['node_errors']}")
                return payload["prompt_id"]
            if resp.status_code == 503 and time.monotonic() < deadline:
                time.sleep(10.0)  # container booting ComfyUI; keep waiting
                continue
            raise EngineError(f"/prompt {resp.status_code}: {resp.text[:500]}")

    def poll(self, prompt_id: str) -> dict | None:
        """Return the history entry when finished, else None."""
        with self._client() as client:
            resp = client.get(f"/history/{prompt_id}")
        if resp.status_code != 200:
            return None
        entry = resp.json().get(prompt_id)
        if not entry:
            return None
        status = entry.get("status", {})
        if status.get("completed") or status.get("status_str") in ("success", "error"):
            if status.get("status_str") != "success":
                raise EngineError(f"prompt {prompt_id} failed: {status}")
            return entry
        return None

    def run(self, workflow: dict) -> tuple[str, dict]:
        """Submit and wait; returns (prompt_id, history_entry)."""
        prompt_id = self.submit(workflow)
        deadline = time.monotonic() + self.max_wait
        while time.monotonic() < deadline:
            entry = self.poll(prompt_id)
            if entry is not None:
                return prompt_id, entry
            time.sleep(self.poll_interval)
        raise EngineError(f"timed out waiting for prompt {prompt_id}")

    def download(self, item: dict) -> bytes:
        params = {
            "filename": item["filename"],
            "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        }
        with self._client() as client:
            resp = client.get("/view", params=params)
        resp.raise_for_status()
        return resp.content
