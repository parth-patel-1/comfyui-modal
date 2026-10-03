"""Generation worker: claims queued jobs (SKIP LOCKED) and drives them
through the ComfyUI engines, then settles credits atomically.

Run with: python -m app.worker.loop   (from backend/)
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

from app.core.config import get_settings
from app.core.db import db_conn
from app.services import storage
from app.services.engines import EngineClient, EngineError

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("genstudio.worker")

# workflow_factory lives in modal_app/ (pure python, no modal import needed)
sys.path.insert(0, str(Path(__file__).parents[3] / "modal_app"))
import workflow_factory as factory  # noqa: E402


CLAIM_SQL = """
with next_job as (
    select id from public.generations
    where status = 'queued' and engine = %s
    order by created_at
    for update skip locked
    limit 1
)
update public.generations g
set status = 'provisioning', progress = 10, started_at = now(), gpu_type = coalesce((
    select case when g.engine = 'image'
                then ms.image_gpu else ms.video_gpu end
    from public.modal_settings ms where ms.id = 1
), '')
from next_job q
where g.id = q.id
returning g.id, g.user_id, g.engine, g.mode, g.prompt, g.negative_prompt,
          g.params, g.reference_paths, g.credits_charged, g.gpu_type
"""

PROGRESS_SQL = ("update public.generations set status = %s, progress = %s, "
                "comfy_prompt_id = %s, eta_seconds = %s where id = %s")

# Rough wall-clock targets used to interpolate progress between the coarse
# stage markers (claimed 10 -> refs 20 -> submitted 40 -> ComfyUI 40..79 ->
# uploading 80 -> settled 100). Only a UX estimate; 100 always comes from
# settle_generation.
EXPECTED_SECONDS = {"image": 60.0, "video": 960.0}  # measured on L40S: 20 steps x ~49s/it ≈ 16 min (Modal logs Oct 3)


def _claim(engine: str) -> dict | None:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(CLAIM_SQL, (engine,))
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None
        cols = [d[0] for d in cur.description]
        conn.commit()
    return dict(zip(cols, row))


def _set_progress(job_id: str, status: str, progress: int,
                  comfy_prompt_id: str = "", eta_s: int | None = None) -> None:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(PROGRESS_SQL, (status, progress, comfy_prompt_id, eta_s, job_id))
        conn.commit()


def _job_status(job_id: str) -> str | None:
    """Current status of a generation row (cheap; used to honor cancels)."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("select status from public.generations where id = %s", (job_id,))
        row = cur.fetchone()
    return row[0] if row else None


def _engine_url(engine: str) -> str:
    """Endpoint from modal_settings (runtime-changeable); env fallback."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select image_endpoint, video_endpoint from public.modal_settings where id = 1"
        )
        img, vid = cur.fetchone()
    s = get_settings()
    return (img if engine == "image" else vid) or (
        s.image_engine_url if engine == "image" else s.video_engine_url
    )


def _build_workflow(job: dict, ref_names: list[str]) -> dict:
    p = job["params"] if isinstance(job["params"], dict) else dict(job["params"])
    seed = int(p.get("seed", int(time.time()) % (2**31)))
    steps = int(p.get("steps", 25))
    cfg = float(p.get("cfg", 1.0))
    mode = job["mode"]
    if mode == "t2i":
        return factory.build_image_t2i(
            job["prompt"], job["negative_prompt"], p["width"], p["height"],
            seed=seed, steps=steps, cfg=cfg)
    if mode == "edit":
        return factory.build_image_edit(
            job["prompt"], job["negative_prompt"], ref_names,
            p["width"], p["height"], seed=seed, steps=steps, cfg=cfg)
    if mode == "t2v":
        return factory.build_video_t2v(
            job["prompt"], p["width"], p["height"], int(p.get("duration_s", 5)),
            seed=seed, steps=steps, turbo=bool(p.get("turbo")))
    return factory.build_video_i2v(
        job["prompt"], ref_names[0], ref_names[1] if len(ref_names) > 1 else None,
        p["width"], p["height"], int(p.get("duration_s", 5)),
        seed=seed, steps=steps, turbo=bool(p.get("turbo")))


def _settle(job_id: str, success: bool, error: str = "", duration_ms=None,
            outputs=None, cost_compute=None, cost_billed=None) -> None:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select public.settle_generation(%s::uuid, %s::boolean, %s::text, "
            "%s::int, %s::numeric, %s::numeric, %s::text[])",
            (job_id, success, error, duration_ms,
             cost_compute, cost_billed, outputs or []),
        )
        conn.commit()


def _costs(duration_ms: int, gpu_type: str) -> tuple[float | None, float | None]:
    """(compute_usd, billed_est_usd) from gpu_rates + overhead factor."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("select hourly_usd from public.gpu_rates where gpu_type = %s", (gpu_type,))
        rate = cur.fetchone()
        cur.execute("select overhead_factor from public.modal_settings where id = 1")
        factor = cur.fetchone()
    if not rate:
        return None, None
    compute = float(rate[0]) * duration_ms / 3_600_000.0
    billed = compute * float(factor[0] if factor else 1.25)
    return round(compute, 6), round(billed, 6)


def _process(job: dict) -> None:
    job_id = str(job["id"])
    user_id = str(job["user_id"])
    started = time.monotonic()
    client = EngineClient(_engine_url(job["engine"]))

    try:
        # 0) wake the engine if it is cold (scaled to zero on Modal) --
        #    blocks up to cold_start_wait_s instead of failing the job
        client.wait_ready()

        # 1) fetch user references from Storage and upload to the engine
        ref_names: list[str] = []
        for i, path in enumerate(list(job["reference_paths"]), start=1):
            data = storage.download("references", path)
            ext = path.rsplit(".", 1)[-1].lower()
            ref_names.append(client.upload_image(data, f"gen_{job_id[:8]}_{i}.{ext}"))
        _set_progress(job_id, "running", 20)

        # 2) build + submit workflow (client_id = prompt_id so ComfyUI's
        #    websocket events can be correlated back to this job)
        workflow = _build_workflow(job, ref_names)
        prompt_id = client.submit(workflow, client_id=job_id)
        _set_progress(job_id, "running", 40, comfy_prompt_id=prompt_id)
        log.info("job %s submitted as prompt %s", job_id, prompt_id)

        # 2b) background websocket listener: real per-step progress + a
        #     measured ETA (avg step time x remaining steps) written to the
        #     DB as each step completes. The HTTP poll below still decides
        #     completion; this only makes the UI truthful.
        step_state = {"t0": None}

        def _on_step(value: int, total: int) -> None:
            now = time.monotonic()
            progress = min(88, 40 + int(45 * value / total))
            if step_state["t0"] is None:
                # first completed step: estimate from the engine's expected
                # total duration; refined by measurement on later steps
                step_state["t0"] = now
                per_step = EXPECTED_SECONDS.get(job["engine"], 120.0) / total
            else:
                per_step = (now - step_state["t0"]) / max(1, value - 1)
            remaining = total - value
            eta = int(remaining * per_step + 90)  # +90s for VAE decode/encode
            _set_progress(job_id, "running", progress, comfy_prompt_id=prompt_id,
                          eta_s=eta)
            log.info("job %s step %d/%d -> progress %d%%, eta %ds",
                     job_id, value, total, progress, eta)

        watcher = threading.Thread(target=client.watch_progress,
                                   args=(prompt_id, _on_step), daemon=True)
        watcher.start()

        # 3) wait for completion via HTTP /history (source of truth)
        deadline = time.monotonic() + get_settings().job_timeout_s
        expected = EXPECTED_SECONDS.get(job["engine"], 120.0)
        submitted_at = time.monotonic()
        last_progress = 40
        entry = None
        while time.monotonic() < deadline:
            # honor a user cancel while the engine runs: the RPC has already
            # refunded credits and set status='canceled'; abort the prompt
            # server-side and stop without settling anything
            if _job_status(job_id) == "canceled":
                client.interrupt()
                log.info("job %s canceled by user mid-run; prompt aborted", job_id)
                return
            entry = client.poll(prompt_id)
            if entry is not None:
                break
            share = min(1.0, (time.monotonic() - submitted_at) / expected)
            p = 40 + int(39 * share)
            if p != last_progress:
                _set_progress(job_id, "running", p, comfy_prompt_id=prompt_id)
                last_progress = p
            time.sleep(client.poll_interval)
        if entry is None:
            raise EngineError("engine timed out")
        if _job_status(job_id) == "canceled":
            # cancel landed between the last check and completion; engine
            # output exists but ownership of the outcome belongs to the user
            log.info("job %s canceled just before completion; skipping settle", job_id)
            return
        _set_progress(job_id, "uploading", 90, eta_s=None)

        # 4) download outputs and publish to Storage under the user's folder
        outputs: list[str] = []
        outputs_node = entry.get("outputs", {})
        for node_out in outputs_node.values():
            files = (node_out.get("images") or node_out.get("gifs")
                     or node_out.get("videos") or [])
            for f in files:
                blob = client.download(f)
                fname = f"{prompt_id}_{len(outputs)}_{f['filename']}"
                ctype = "video/mp4" if fname.endswith(".mp4") else "image/png"
                path = f"{user_id}/{job_id}/{fname}"
                storage.upload("generations", path, blob, ctype)
                outputs.append(path)
        if not outputs:
            raise EngineError("engine produced no output files")

        # 5) settle with costs
        duration_ms = int((time.monotonic() - started) * 1000)
        gpu = job.get("gpu_type") or ""
        compute, billed = _costs(duration_ms, gpu) if gpu else (None, None)
        _settle(job_id, True, duration_ms=duration_ms, outputs=outputs,
                cost_compute=compute, cost_billed=billed)
        log.info("job %s succeeded (%d outputs, %.1fs)", job_id, len(outputs),
                 duration_ms / 1000)

    except Exception as e:  # noqa: BLE001 -- any failure refunds credits
        log.exception("job %s failed", job_id)
        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            _settle(job_id, False, error=str(e)[:2000], duration_ms=duration_ms)
        except Exception:  # noqa: BLE001
            log.exception("settle failed for %s", job_id)


def _slots(engine: str) -> int:
    """Concurrent job slots for an engine (app_settings.worker_parallel_slots)."""
    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute("select worker_parallel_slots from public.app_settings where id = 1")
            row = cur.fetchone()
        return max(1, int(row[0])) if row else 1
    except Exception:  # noqa: BLE001 -- never let a settings glitch stop claiming
        log.exception("worker[%s] could not read worker_parallel_slots; using 1", engine)
        return 1


def run_forever(engine: str) -> None:
    """Worker loop for one engine (image or video).

    Runs up to app_settings.worker_parallel_slots jobs CONCURRENTLY per
    engine: each claimed job gets its own thread, so a batch of queued jobs
    drains in parallel (SKIP LOCKED guarantees no double-claim). A separate
    loop per engine keeps the two generation types independent: a long-running
    video job never blocks image jobs and vice versa.
    """
    interval = get_settings().worker_poll_interval_s
    log.info("worker[%s] started (poll %.1fs)", engine, interval)
    active: list[threading.Thread] = []
    while True:
        try:
            active = [t for t in active if t.is_alive()]
            slots = _slots(engine)
            while len(active) < slots:
                job = _claim(engine)
                if job is None:
                    break
                log.info("worker[%s] claimed job %s (%d/%d slots busy)",
                         engine, job["id"], len(active) + 1, slots)
                t = threading.Thread(target=_process, args=(job,), daemon=True)
                t.start()
                active.append(t)
        except Exception:  # noqa: BLE001
            log.exception("worker[%s] claim failed", engine)
        time.sleep(interval)


if __name__ == "__main__":
    import threading

    threads = [threading.Thread(target=run_forever, args=(e,), daemon=True)
               for e in ("image", "video")]
    for t in threads:
        t.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log.info("worker stopped")