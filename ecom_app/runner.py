"""Threaded drivers for UI shells (Streamlit): pipeline + video jobs.

``PipelineRunner`` drives the LangGraph shoot in a background thread: stdout
from the nodes is captured into a line buffer, and human-in-the-loop
``interrupt()`` payloads surface as plain dicts the UI renders before calling
``answer()``. ``VideoJob`` does the same for a (long) MiniMax H3 video render.
Both are UI-agnostic so they can be tested headless.
"""

from __future__ import annotations

import contextlib
import io
import threading
import time
from pathlib import Path

import requests
from langgraph.types import Command


class _LogCapture(io.TextIOBase):
    """File-like object that appends complete lines to a shared list."""

    def __init__(self, sink: list):
        self._sink = sink
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._sink.append(line)
        return len(s)

    def flush(self) -> None:
        if self._buf.strip():
            self._sink.append(self._buf)
        self._buf = ""


def _ts(msg: str) -> str:
    return "[" + time.strftime("%H:%M:%S") + "] " + msg


class PipelineRunner:
    """Runs one LangGraph shoot (with interrupt hand-off) in a thread."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.status = "idle"  # idle | running | waiting | done | error
        self.interrupt = None
        self.result = None
        self.error = None
        self.logs = []
        self._graph = None
        self._config = None
        self._thread = None

    # -- control -----------------------------------------------------------
    def start(self, graph, config: dict, state: dict) -> None:
        if self.status in ("running", "waiting"):
            raise RuntimeError("a shoot is already in progress")
        self.reset()
        self._graph, self._config = graph, config
        self._spawn(state)

    def answer(self, value) -> None:
        """Resume from the pending interrupt with the user's answer."""
        if self.status != "waiting":
            raise RuntimeError("no question is pending")
        self.interrupt = None
        self._spawn(Command(resume=value))

    # -- internals ----------------------------------------------------------
    def _spawn(self, arg) -> None:
        self.status = "running"
        self._thread = threading.Thread(target=self._run, args=(arg,), daemon=True)
        self._thread.start()

    def _run(self, arg) -> None:
        capture = _LogCapture(self.logs)
        try:
            with contextlib.redirect_stdout(capture):
                result = self._graph.invoke(arg, self._config)
        except Exception as e:  # surface node errors to the UI
            self.error = f"{type(e).__name__}: {e}"
            self.status = "error"
            return
        if "__interrupt__" in result:
            self.interrupt = result["__interrupt__"][0].value
            self.status = "waiting"
        else:
            self.result = result
            self.status = "done"


class VideoJob:
    """Submits one MiniMax H3 video workflow and downloads the MP4."""

    SAVE_NODE = "14"

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.status = "idle"  # idle | running | done | error
        self.error = None
        self.logs = []
        self.files = []
        self.prompt_id = None
        self._thread = None

    def start(self, comfy, workflow: dict, out_dir, poll_interval: int = 15) -> None:
        if self.status == "running":
            raise RuntimeError("a video job is already running")
        self.reset()
        self.status = "running"
        self._thread = threading.Thread(
            target=self._run, args=(comfy, workflow, Path(out_dir), poll_interval), daemon=True
        )
        self._thread.start()

    def _log(self, msg: str) -> None:
        self.logs.append(_ts(msg))

    def _run(self, comfy, workflow: dict, out_dir: Path, poll_interval: int) -> None:
        try:
            self._log("submitting MiniMax H3 workflow ...")
            prompt_id = comfy.submit(workflow)
            self.prompt_id = prompt_id
            self._log(
                "queued prompt_id=" + prompt_id + "; waiting for the GPU "
                "(cold start loads ~42 GB of video models, this can take a while)"
            )
            deadline = time.time() + comfy.max_wait
            while time.time() < deadline:
                try:
                    hist = requests.get(
                        comfy.base_url + "/history/" + prompt_id, timeout=60
                    ).json()
                except requests.RequestException as e:
                    self._log(f"history poll failed ({e}); retrying")
                    time.sleep(poll_interval)
                    continue
                entry = hist.get(prompt_id)
                if entry:
                    status = entry.get("status", {})
                    if status.get("completed") or status.get("status_str") in ("success", "error"):
                        if status.get("status_str") != "success":
                            raise RuntimeError(f"video prompt failed: {status}")
                        self._log("render finished; downloading MP4 ...")
                        saved = comfy.download_images(entry, self.SAVE_NODE, out_dir)
                        self.files = [str(p) for p in saved]
                        for p in saved:
                            self._log(f"saved {p} ({p.stat().st_size / 1e6:.1f} MB)")
                        self.status = "done"
                        return
                time.sleep(poll_interval)
            raise RuntimeError("timed out waiting for the video render")
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.status = "error"