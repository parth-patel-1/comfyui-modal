"""Generation endpoints: create, list, inspect, cancel + wallet + uploads."""

from __future__ import annotations

import json
import uuid

import psycopg
from fastapi import APIRouter, HTTPException, Query, Response

from app.core.db import db_conn
from app.dependencies import UserDep
from app.schemas.models import GenerationCreate, GenerationOut, UploadTicket, WalletOut
from app.services import storage

router = APIRouter(prefix="/api", tags=["generations"])

# errors raised by request_generation RPC -> HTTP status
_RPC_STATUS = {
    "MAINTENANCE_MODE": 503,
    "ACCOUNT_SUSPENDED": 403,
    "TOO_MANY_ACTIVE_JOBS": 429,
    "DAILY_CAP_REACHED": 429,
    "INSUFFICIENT_CREDITS": 402,
    "WALLET_NOT_FOUND": 403,
    "PROFILE_NOT_FOUND": 403,
}

_VALID_MODES = {"image": {"t2i", "edit"}, "video": {"t2v", "i2v"}}


def _http_for_rpc_error(msg: str) -> HTTPException:
    code = msg.split(":", 1)[0]
    status = _RPC_STATUS.get(code, 400)
    detail = msg.split(":", 1)[1] if ":" in msg else code.lower()
    return HTTPException(status, detail.replace("_", " "))


def _load_engine_cfg(conn: psycopg.Connection, engine: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "select params from public.engine_configs where engine = %s and enabled",
            (engine,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(400, f"engine {engine} is not available")
    return row[0] if isinstance(row[0], dict) else json.loads(row[0])


def _clamp(value, spec, name):
    lo, hi, step = spec.get("min", 0), spec.get("max", 10**9), spec.get("step")
    try:
        v = type(lo)(value)
    except (TypeError, ValueError):
        raise HTTPException(422, f"invalid {name}")
    v = max(lo, min(hi, v))
    if step:
        v = round(v / step) * step
    return v


def _validate_params(cfg: dict, engine: str, mode: str, params: dict,
                     ref_count: int) -> dict:
    out = dict(params)
    if mode in ("t2i", "edit"):
        res = cfg["resolution"]
        out["width"] = _clamp(params.get("width", res["default"]), res, "width")
        out["height"] = _clamp(params.get("height", res["default"]), res, "height")
        out["steps"] = _clamp(params.get("steps", cfg["steps"]["default"]),
                              cfg["steps"], "steps")
        out["cfg"] = _clamp(params.get("cfg", cfg["cfg"]["default"]),
                            cfg["cfg"], "cfg")
        max_refs = cfg.get("max_reference_images", 16)
        if mode == "edit":
            if ref_count < 1:
                raise HTTPException(422, "edit mode requires at least one reference")
            if ref_count > max_refs:
                raise HTTPException(422, f"too many references (max {max_refs})")
    else:
        out["duration_s"] = _clamp(params.get("duration_s",
                                              cfg["duration_s"]["default"]),
                                    cfg["duration_s"], "duration_s")
        out["steps"] = _clamp(params.get("steps", cfg["steps"]["default"]),
                              cfg["steps"], "steps")
        resolutions = [tuple(r) for r in cfg.get("resolutions", [])]
        want = (int(params.get("width", 864)), int(params.get("height", 480)))
        if resolutions and want not in resolutions:
            raise HTTPException(422, f"unsupported video resolution {want}")
        out["width"], out["height"] = want
        out["turbo"] = bool(params.get("turbo", False))
        max_refs = cfg.get("max_reference_images", 2)
        if mode == "i2v":
            if ref_count < 1:
                raise HTTPException(422, "i2v requires a first frame")
            if ref_count > max_refs:
                raise HTTPException(422, f"i2v supports at most {max_refs} frames")
    return out


@router.post("/generations", status_code=201)
def create_generation(body: GenerationCreate, user: UserDep) -> dict:
    if body.mode not in _VALID_MODES[body.engine]:
        raise HTTPException(422, f"mode {body.mode} not valid for {body.engine}")
    for ref in body.reference_paths:
        if not ref.startswith(f"{user.id}/"):
            raise HTTPException(403, "reference path outside your folder")

    with db_conn() as conn:
        cfg = _load_engine_cfg(conn, body.engine)
        params = _validate_params(cfg, body.engine, body.mode,
                                  body.params, len(body.reference_paths))
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "select * from public.request_generation(%s, %s, %s, %s, %s, %s, %s, %s)",
                    (user.id, body.engine, body.mode, body.prompt,
                     body.negative_prompt, json.dumps(params),
                     body.reference_paths, ""),
                )
            except psycopg.errors.DatabaseError as e:
                conn.rollback()
                if (getattr(e, "sqlstate", "") or "")[:2] != "P0":
                    raise  # not a RAISE EXCEPTION from the RPC
                msg = getattr(getattr(e, "diag", None), "message_primary", None) \
                    or str(e).split("\n")[0].strip()
                raise _http_for_rpc_error(msg)
            generation_id, credits = cur.fetchone()
            conn.commit()
            cur.execute(
                "select id, engine, mode, status, progress, started_at, prompt, "
                "params, reference_paths, credits_charged, error, output_paths, "
                "created_at, finished_at from public.generations where id = %s",
                (generation_id,),
            )
            row = cur.fetchone()

    # submit-time warm-up: the moment a job is accepted, start booting that
    # engine's GPU in the background so the worker finds it warm (or nearly)
    # instead of waking it itself
    from app.routers.engines import kick_warm  # local import avoids a cycle
    kick_warm(body.engine)

    keys = ["id", "engine", "mode", "status", "progress", "started_at", "prompt",
            "params", "reference_paths", "credits_charged", "error", "output_paths",
            "created_at", "finished_at"]
    return dict(zip(keys, row))


@router.get("/generations")
def list_generations(
    user: UserDep,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, engine, mode, status, progress, started_at, prompt, params, "
            "reference_paths, credits_charged, error, output_paths, "
            "created_at, finished_at, gpu_type, eta_seconds from "
            "public.generations "
            "where user_id = %s order by created_at desc limit %s offset %s",
            (user.id, limit, offset),
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


@router.get("/generations/{generation_id}")
def get_generation(generation_id: uuid.UUID, user: UserDep) -> dict:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, user_id, engine, mode, status, progress, started_at, prompt, "
            "params, reference_paths, credits_charged, error, output_paths, "
            "created_at, finished_at, gpu_type, eta_seconds from "
            "public.generations where id = %s",
            (generation_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "generation not found")
        cols = [d[0] for d in cur.description]
        gen = dict(zip(cols, row))
    if str(gen.pop("user_id")) != user.id and user.role != "admin":
        raise HTTPException(404, "generation not found")
    return gen


_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "gif": "image/gif",
}


def _download_filename(generation_id: uuid.UUID, n: int, path: str) -> str:
    """Unique, traceable download name: genstudio_<generation_id>_<index>.<ext>.

    The generation id maps 1:1 to the public.generations row, which records the
    owner and the exact storage paths (generations bucket), so any downloaded
    file can always be located on the server.
    """
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else "png"
    return f"genstudio_{generation_id}_{n}.{ext}"


@router.get("/generations/{generation_id}/download")
def download_output(
    generation_id: uuid.UUID,
    user: UserDep,
    n: int = Query(0, ge=0, description="index of the output file"),
    dl: bool = Query(False, description="true = force download, false = inline"),
) -> Response:
    """Stream one output of a generation. Owner or admin only.

    With dl=1 the browser saves the file under its unique server-side name
    (genstudio_<generation_id>_<n>.<ext>) instead of displaying it inline.
    """
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select user_id, output_paths from public.generations where id = %s",
            (generation_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, "generation not found")
    if str(row[0]) != user.id and user.role != "admin":
        raise HTTPException(404, "generation not found")
    paths = row[1] or []
    if n >= len(paths):
        raise HTTPException(404, "output not found")
    path = paths[n]
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else "png"
    try:
        blob = storage.download("generations", path)
    except storage.StorageError as e:
        raise HTTPException(502, str(e)) from e
    headers = {"Cache-Control": "private, max-age=600"}
    if dl:
        name = _download_filename(generation_id, n, path)
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return Response(
        content=blob,
        media_type=_CONTENT_TYPES.get(ext, "application/octet-stream"),
        headers=headers,
    )


@router.post("/generations/{generation_id}/cancel")
def cancel_generation(generation_id: uuid.UUID, user: UserDep) -> dict:
    with db_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("select public.cancel_generation(%s::uuid, %s::uuid)",
                        (generation_id, user.id))
            conn.commit()
        except psycopg.errors.DatabaseError as e:
            conn.rollback()
            if (getattr(e, "sqlstate", "") or "")[:2] != "P0":
                raise  # not a RAISE EXCEPTION from the RPC
            msg = getattr(getattr(e, "diag", None), "message_primary", None) \
                or str(e).split("\n")[0].strip()
            raise _http_for_rpc_error(msg)
    return {"status": "canceled"}


@router.post("/generations/{generation_id}/retry")
def retry_generation(generation_id: uuid.UUID, user: UserDep) -> dict:
    """Re-queue a failed or canceled generation with identical inputs.

    Creates a NEW generation row via the same request_generation RPC as a
    normal create (credits are charged again; the automatic refund on
    failure still applies). The original row is left untouched for history.
    """
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select engine, mode, prompt, negative_prompt, params, "
            "reference_paths, status from public.generations where id = %s",
            (generation_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, "generation not found")
    engine, mode, prompt, negative_prompt, params, reference_paths, status = row
    if status not in ("failed", "canceled"):
        raise HTTPException(409, f"cannot retry a generation with status '{status}'")

    body = GenerationCreate(
        engine=engine, mode=mode, prompt=prompt,
        negative_prompt=negative_prompt or "",
        params=params if isinstance(params, dict) else json.loads(params or "{}"),
        reference_paths=reference_paths or [],
    )
    return create_generation(body, user)


@router.get("/me")
def me(user: UserDep) -> dict:
    """Caller identity for the UI (role drives the Admin nav link)."""
    return {"id": user.id, "email": user.email, "role": user.role}


@router.get("/wallet", response_model=WalletOut)
def wallet(user: UserDep) -> WalletOut:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("select balance from public.credit_wallets where user_id = %s",
                    (user.id,))
        row = cur.fetchone()
    return WalletOut(balance=row[0] if row else 0)


@router.post("/uploads/ticket", response_model=UploadTicket)
def upload_ticket(user: UserDep, filename: str = Query(min_length=1)) -> UploadTicket:
    """Browser uploads directly to Storage using its own user JWT;
    this just tells it the target path (references/{uid}/{uuid}.<ext>)."""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        raise HTTPException(422, "unsupported file type")
    path = f"{user.id}/{uuid.uuid4()}.{ext}"
    return UploadTicket(bucket="references", path=path, upload_url="", max_bytes=26214400)