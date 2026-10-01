"""Admin panel endpoints: overview stats, users, settings, pricing, GPU + deploys.

Every route requires the admin role (AdminDep). Every mutation is recorded in
admin_audit_log.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import uuid
from pathlib import Path

import httpx
import psycopg
from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.core.db import db_conn
from app.dependencies import AdminDep
from app.schemas.models import (
    AdminCreditsBody,
    AdminCreateUserBody,
    AdminStatusBody,
    AppSettingsUpdate,
    ModalSettingsUpdate,
    PricingUpdate,
    TemplateBody,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# deploy_config.json lives next to the modal apps; both engine apps read it.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_CONFIG_PATH = REPO_ROOT / "modal_app" / "deploy_config.json"
ENGINE_APPS = {"image": REPO_ROOT / "modal_app" / "image_app.py",
               "video": REPO_ROOT / "modal_app" / "video_app.py"}


def _audit(conn: psycopg.Connection, admin_id: str, action: str,
           target: str = "", payload: dict | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.admin_audit_log (admin_id, action, target, payload) "
            "values (%s, %s, %s, %s)",
            (admin_id, action, target, json.dumps(payload or {})),
        )


def _rows_as_dicts(cur: psycopg.Cursor) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


NUMERIC_FIELDS = {"gpu_seconds", "compute_usd", "billed_usd", "hourly_usd",
                  "credits_charged"}


def _as_floats(rows: list[dict]) -> list[dict]:
    """psycopg returns numeric as Decimal; emit plain floats for JSON."""
    return [{**r, **{k: float(r[k]) for k in NUMERIC_FIELDS & r.keys()}}
            for r in rows]


# --------------------------------------------------------------------- overview

@router.get("/overview")
def overview(admin: AdminDep) -> dict:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from public.profiles")
        users = cur.fetchone()[0]
        cur.execute("select count(*) from public.profiles where status = 'suspended'")
        suspended = cur.fetchone()[0]
        cur.execute("select count(*) from public.generations")
        generations = cur.fetchone()[0]
        cur.execute(
            "select count(*) from public.generations "
            "where status in ('queued','provisioning','running','uploading')"
        )
        active = cur.fetchone()[0]
        cur.execute(
            "select count(*) from public.generations "
            "where created_at >= date_trunc('day', now())"
        )
        today = cur.fetchone()[0]
        cur.execute(
            "select count(*) filter (where status = 'succeeded'), "
            "count(*) filter (where status = 'failed') "
            "from public.generations where created_at >= date_trunc('day', now())"
        )
        ok_today, failed_today = cur.fetchone()
        cur.execute("select coalesce(sum(balance), 0) from public.credit_wallets")
        credits = cur.fetchone()[0]
        cur.execute(
            "select id, status, trigger_reason, started_at, finished_at "
            "from public.deploy_runs order by started_at desc limit 1"
        )
        last = _rows_as_dicts(cur)
        cur.execute(
            "select site_name, maintenance_mode from public.app_settings where id = 1"
        )
        site, maintenance = cur.fetchone()
    return {
        "users": users,
        "suspended_users": suspended,
        "generations_total": generations,
        "generations_active": active,
        "generations_today": today,
        "succeeded_today": ok_today,
        "failed_today": failed_today,
        "credits_in_circulation": credits,
        "maintenance_mode": maintenance,
        "site_name": site,
        "last_deploy": last[0] if last else None,
    }


# --------------------------------------------------------------------- spending

# Cost columns (cost_compute_usd / cost_billed_est_usd) are only written when a
# job settles successfully, so money aggregates run over succeeded generations.
@router.get("/spending")
def spending(
    admin: AdminDep,
    days: int = Query(30, ge=0, le=3650, description="0 = all time"),
) -> dict:
    where = "where g.status = 'succeeded'"
    params_all: list = []
    if days > 0:
        where += " and g.created_at >= now() - make_interval(days => %s)"
        params_all.append(days)

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*), "
            "coalesce(sum(g.duration_ms), 0) / 1000.0, "
            "coalesce(sum(g.cost_compute_usd), 0), "
            "coalesce(sum(g.cost_billed_est_usd), 0), "
            "coalesce(sum(g.credits_charged), 0) "
            f"from public.generations g {where}",
            params_all,
        )
        (jobs, gpu_s, compute, billed, credits) = cur.fetchone()

        cur.execute(
            "select count(*) from public.generations g "
            "where g.status = 'failed'"
            + (" and g.created_at >= now() - make_interval(days => %s)" if days > 0 else ""),
            params_all,
        )
        failed = cur.fetchone()[0]

        cur.execute(
            "select coalesce(nullif(g.gpu_type, ''), 'unknown') as gpu, "
            "count(*) as jobs, "
            "coalesce(sum(g.duration_ms), 0) / 1000.0 as gpu_seconds, "
            "coalesce(sum(g.cost_compute_usd), 0) as compute_usd, "
            "coalesce(sum(g.cost_billed_est_usd), 0) as billed_usd, "
            "coalesce(max(r.hourly_usd), 0) as hourly_usd "
            f"from public.generations g "
            "left join public.gpu_rates r on r.gpu_type = g.gpu_type "
            f"{where} group by 1 order by compute_usd desc",
            params_all,
        )
        by_gpu = _as_floats(_rows_as_dicts(cur))

        cur.execute(
            "select g.engine, count(*) as jobs, "
            "coalesce(sum(g.duration_ms), 0) / 1000.0 as gpu_seconds, "
            "coalesce(sum(g.cost_compute_usd), 0) as compute_usd, "
            "coalesce(sum(g.cost_billed_est_usd), 0) as billed_usd "
            f"from public.generations g {where} group by 1 order by compute_usd desc",
            params_all,
        )
        by_engine = _as_floats(_rows_as_dicts(cur))

        cur.execute(
            "select p.id as user_id, p.email, p.display_name, count(*) as jobs, "
            "coalesce(sum(g.duration_ms), 0) / 1000.0 as gpu_seconds, "
            "coalesce(sum(g.cost_compute_usd), 0) as compute_usd, "
            "coalesce(sum(g.cost_billed_est_usd), 0) as billed_usd, "
            "coalesce(sum(g.credits_charged), 0) as credits_charged "
            "from public.generations g join public.profiles p on p.id = g.user_id "
            f"{where} group by 1, 2, 3 order by compute_usd desc limit 100",
            params_all,
        )
        by_user = _as_floats(_rows_as_dicts(cur))

        day_where = where
        cur.execute(
            "select date_trunc('day', g.created_at)::date as day, "
            "count(*) as jobs, "
            "coalesce(sum(g.duration_ms), 0) / 1000.0 as gpu_seconds, "
            "coalesce(sum(g.cost_compute_usd), 0) as compute_usd, "
            "coalesce(sum(g.cost_billed_est_usd), 0) as billed_usd "
            f"from public.generations g {day_where} "
            "group by 1 order by 1 desc limit 120",
            params_all,
        )
        by_day = _as_floats(_rows_as_dicts(cur))

    return {
        "days": days,
        "totals": {
            "jobs": jobs,
            "failed_jobs": failed,
            "gpu_seconds": float(gpu_s),
            "compute_usd": float(compute),
            "billed_est_usd": float(billed),
            "credits_charged": float(credits),
        },
        "by_gpu": by_gpu,
        "by_engine": by_engine,
        "by_user": by_user,
        "by_day": by_day,
    }


# ------------------------------------------------------------------------ users

@router.get("/users")
def list_users(
    admin: AdminDep,
    q: str = Query("", max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    pat = f"%{q}%"
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select p.id, p.email, p.display_name, p.role, p.status, p.created_at, "
            "coalesce(w.balance, 0) as balance, "
            "(select count(*) from public.generations g where g.user_id = p.id) "
            "  as generations, "
            "(select coalesce(sum(g.credits_charged), 0) from public.generations g "
            "  where g.user_id = p.id and g.status = 'succeeded') as credits_spent "
            "from public.profiles p "
            "left join public.credit_wallets w on w.user_id = p.id "
            "where p.email ilike %s or p.display_name ilike %s "
            "order by p.created_at desc limit %s offset %s",
            (pat, pat, limit, offset),
        )
        return _rows_as_dicts(cur)


@router.post("/users")
def create_user(body: AdminCreateUserBody, admin: AdminDep) -> dict:
    """Manually provision a user account with a known password.

    Uses the same Supabase signup endpoint as normal registration (the
    on_auth_user_created trigger then provisions the profile row, wallet
    and signup grant), then confirms the email and aligns the auth rows
    via direct SQL — same approach as scripts/setup_users.py — so the
    user can log in immediately without a confirmation email.
    """
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "invalid email address")
    s = get_settings()
    with db_conn() as conn, conn.cursor() as cur:
        # GoTrue answers an existing email with a 200 + phantom id, so check first
        cur.execute("select id from auth.users where email = %s", (email,))
        if cur.fetchone():
            raise HTTPException(400, "email already registered")

        # Preferred path: the normal signup endpoint. The on_auth_user_created
        # trigger provisions the profile row, wallet and signup grant.
        uid = None
        data: dict = {}
        try:
            resp = httpx.post(
                f"{s.supabase_url}/auth/v1/signup",
                json={
                    "email": email,
                    "password": body.password,
                    "data": {"name": body.display_name} if body.display_name else {},
                },
                headers={"apikey": s.supabase_anon_key},
                timeout=30,
            )
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if resp.status_code in (200, 201) and data.get("id"):
                uid = data["id"]
            elif "already" in str(data.get("msg", "")).lower() or \
                    data.get("error_code") == "user_already_exists":
                raise HTTPException(400, "email already registered")
        except httpx.HTTPError:
            data = {}  # network failure -> fall through to the SQL path

        if uid is None:
            # Fallback (signup 429 / network issue): insert the auth row
            # directly with a pgcrypto bcrypt hash — no confirmation email.
            # Mirrors scripts/setup_users.py.
            meta = json.dumps({"name": body.display_name, "email": email,
                               "email_verified": True})
            cur.execute(
                "insert into auth.users "
                "(id, instance_id, aud, role, email, encrypted_password, "
                " email_confirmed_at, raw_app_meta_data, raw_user_meta_data, "
                " created_at, updated_at) "
                "values (gen_random_uuid(), "
                "'00000000-0000-0000-0000-000000000000', 'authenticated', "
                "'authenticated', %s, crypt(%s, gen_salt('bf')), now(), "
                "'{\"provider\":\"email\",\"providers\":[\"email\"]}', %s::jsonb, "
                "now(), now()) returning id",
                (email, body.password, meta),
            )
            uid = cur.fetchone()[0]

        # the row must exist (guards GoTrue's phantom-id replies)
        cur.execute("select id from auth.users where id = %s", (uid,))
        if cur.fetchone() is None:
            raise HTTPException(
                400, f"could not create user: {data.get('msg') or 'signup did not persist'}"
            )
        # confirm email + mirror what a real signup looks like to GoTrue
        cur.execute(
            "update auth.users set email_confirmed_at = now(), updated_at = now() "
            "where id = %s",
            (uid,),
        )
        cur.execute("select count(*) from auth.identities where user_id = %s", (uid,))
        if cur.fetchone()[0] == 0:
            cur.execute(
                "insert into auth.identities "
                "(id, user_id, provider, provider_id, identity_data, "
                " last_sign_in_at, created_at, updated_at) "
                "values (gen_random_uuid(), %s, 'email', %s, "
                "jsonb_build_object('sub', %s::text, 'email', %s::text, "
                "'email_verified', true), now(), now(), now())",
                (uid, uid, uid, email),
            )
        cur.execute(
            "update auth.users set confirmation_token = '', recovery_token = '', "
            "email_change_token_new = '', email_change = '' where id = %s",
            (uid,),
        )
        if body.role == "admin":
            cur.execute(
                "update public.profiles set role = 'admin' where id = %s", (uid,)
            )
        cur.execute(
            "select role, status from public.profiles where id = %s", (uid,)
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            raise HTTPException(500, "profile was not provisioned for the new user")
        balance = None
        if body.grant_credits > 0:
            try:
                cur.execute(
                    "select public.admin_adjust_credits(%s::uuid, %s, %s, %s::uuid)",
                    (uid, body.grant_credits, "admin created user", admin.id),
                )
                balance = cur.fetchone()[0]
            except psycopg.errors.DatabaseError as e:
                conn.rollback()
                msg = getattr(getattr(e, "diag", None), "message_primary", None) \
                    or str(e).split("\n")[0].strip()
                raise HTTPException(400, msg.replace("_", " ").lower()) from e
        _audit(conn, admin.id, "user.create", uid,
               {"email": email, "role": body.role,
                "grant_credits": body.grant_credits})
    return {
        "id": str(uid),
        "email": email,
        "role": body.role,
        "status": "active",
        "balance": balance,
    }


@router.post("/users/{user_id}/credits")
def adjust_credits(user_id: uuid.UUID, body: AdminCreditsBody, admin: AdminDep) -> dict:
    with db_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "select public.admin_adjust_credits(%s::uuid, %s, %s, %s::uuid)",
                (user_id, body.delta, body.note, admin.id),
            )
            balance = cur.fetchone()[0]
        except psycopg.errors.DatabaseError as e:
            conn.rollback()
            if (getattr(e, "sqlstate", "") or "")[:2] != "P0":
                raise  # not a RAISE EXCEPTION from the RPC
            msg = getattr(getattr(e, "diag", None), "message_primary", None) \
                or str(e).split("\n")[0].strip()
            raise HTTPException(400, msg.replace("_", " ").lower())
        _audit(conn, admin.id, "credits.adjust", str(user_id),
               {"delta": body.delta, "note": body.note})
    return {"balance": balance}


@router.post("/users/{user_id}/status")
def set_user_status(user_id: uuid.UUID, body: AdminStatusBody, admin: AdminDep) -> dict:
    if body.status not in ("active", "suspended"):
        raise HTTPException(422, "status must be active or suspended")
    if user_id == uuid.UUID(admin.id):
        raise HTTPException(400, "you cannot change your own status")
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "update public.profiles set status = %s where id = %s returning status",
            (body.status, user_id),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            raise HTTPException(404, "user not found")
        _audit(conn, admin.id, f"user.{body.status}", str(user_id))
    return {"status": row[0]}


# --------------------------------------------------------------------- settings

@router.get("/settings")
def get_settings_all(admin: AdminDep) -> dict:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select site_name, signup_grant_credits, maintenance_mode, "
            "max_concurrent_jobs_per_user, daily_job_cap, "
            "default_negative_prompt_image, default_negative_prompt_video, updated_at "
            "from public.app_settings where id = 1"
        )
        app = _rows_as_dicts(cur)[0]
        cur.execute(
            "select id, engine, base_credits, credits_per_megapixel, "
            "credits_per_ref_image, credits_per_video_second, active "
            "from public.pricing_rules order by engine"
        )
        pricing = _rows_as_dicts(cur)
        cur.execute(
            "select engine, enabled, params from public.engine_configs order by engine"
        )
        engines = [
            {"engine": e, "enabled": en,
             "params": p if isinstance(p, dict) else json.loads(p)}
            for e, en, p in cur.fetchall()
        ]
    return {"app": app, "pricing": pricing, "engines": engines}


@router.put("/settings")
def update_settings(body: AppSettingsUpdate, admin: AdminDep) -> dict:
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(422, "nothing to update")
    cols = ", ".join(f"{k} = %s" for k in fields)
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"update public.app_settings set {cols}, updated_by = %s "
            "where id = 1 returning site_name, maintenance_mode",
            (*fields.values(), admin.id),
        )
        row = cur.fetchone()
        _audit(conn, admin.id, "settings.update", "app_settings", fields)
    return {"site_name": row[0], "maintenance_mode": row[1]}


@router.put("/pricing/{engine}")
def update_pricing(engine: str, body: PricingUpdate, admin: AdminDep) -> dict:
    if engine not in ("image", "video"):
        raise HTTPException(404, "unknown engine")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if engine == "image":
        fields.pop("credits_per_video_second", None)
    if not fields:
        raise HTTPException(422, "nothing to update")
    cols = ", ".join(f"{k} = %s" for k in fields)
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"update public.pricing_rules set {cols} where engine = %s returning id",
            (*fields.values(), engine),
        )
        if cur.fetchone() is None:
            conn.rollback()
            raise HTTPException(404, "pricing rule not found")
        _audit(conn, admin.id, "pricing.update", engine, fields)
    return {"engine": engine, "updated": list(fields)}


@router.put("/engines/{engine}/enabled")
def toggle_engine(engine: str, admin: AdminDep, enabled: bool = Query(...)) -> dict:
    if engine not in ("image", "video"):
        raise HTTPException(404, "unknown engine")
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "update public.engine_configs set enabled = %s where engine = %s "
            "returning engine",
            (enabled, engine),
        )
        if cur.fetchone() is None:
            conn.rollback()
            raise HTTPException(404, "engine not found")
        _audit(conn, admin.id, "engine.toggle", engine, {"enabled": enabled})
    return {"engine": engine, "enabled": enabled}


# --------------------------------------------------------------- modal + deploys

@router.get("/modal")
def get_modal_settings(admin: AdminDep) -> dict:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select image_gpu, video_gpu, image_max_containers, video_max_containers, "
            "image_min_containers, video_min_containers, scaledown_window_s, max_inputs, "
            "overhead_factor, comfyui_version, image_endpoint, video_endpoint, "
            "pending_deploy, updated_at from public.modal_settings where id = 1"
        )
        settings = _rows_as_dicts(cur)[0]
        cur.execute("select gpu_type, hourly_usd from public.gpu_rates order by gpu_type")
        rates = {g: float(h) for g, h in cur.fetchall()}
        cur.execute(
            "select id, trigger_reason, status, started_at, finished_at "
            "from public.deploy_runs order by started_at desc limit 10"
        )
        deploys = _rows_as_dicts(cur)
    return {"settings": settings, "gpu_rates": rates, "deploys": deploys}


@router.put("/modal")
def update_modal_settings(body: ModalSettingsUpdate, admin: AdminDep) -> dict:
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(422, "nothing to update")
    if fields.get("image_min_containers", 0) > fields.get("image_max_containers", 10**9):
        raise HTTPException(422, "image min_containers cannot exceed max_containers")
    if fields.get("video_min_containers", 0) > fields.get("video_max_containers", 10**9):
        raise HTTPException(422, "video min_containers cannot exceed max_containers")
    # fields that require a `modal deploy` to take effect
    deployable = {"image_gpu", "video_gpu", "image_max_containers",
                  "video_max_containers", "image_min_containers",
                  "video_min_containers", "scaledown_window_s",
                  "max_inputs", "comfyui_version"}
    changed_deploy = sorted(deployable & fields.keys())
    cols = ", ".join(f"{k} = %s" for k in fields)
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"update public.modal_settings set {cols}, updated_by = %s "
            "where id = 1 returning image_gpu, video_gpu",
            (*fields.values(), admin.id),
        )
        row = cur.fetchone()
        if changed_deploy:
            cur.execute(
                "update public.modal_settings "
                "set pending_deploy = jsonb_build_object('fields', %s::jsonb, 'at', now()) "
                "where id = 1",
                (json.dumps(changed_deploy),),
            )
        _audit(conn, admin.id, "modal.update", "modal_settings", fields)
    return {"image_gpu": row[0], "video_gpu": row[1],
            "redeploy_recommended": bool(changed_deploy)}


def _write_deploy_config(conn: psycopg.Connection) -> dict:
    """Snapshot modal_settings into deploy_config.json for the Modal apps."""
    with conn.cursor() as cur:
        cur.execute(
            "select comfyui_version, image_gpu, video_gpu, image_max_containers, "
            "video_max_containers, image_min_containers, video_min_containers, "
            "scaledown_window_s, max_inputs from public.modal_settings where id = 1"
        )
        (ver, igpu, vgpu, imax, vmax, imin, vmin, sd, mxin) = cur.fetchone()
    cfg = {
        "comfyui_version": ver,
        "image": {"gpu": igpu, "max_containers": imax, "min_containers": imin,
                  "scaledown_window_s": sd, "max_inputs": mxin,
                  "startup_timeout_s": 1200},
        "video": {"gpu": vgpu, "max_containers": vmax, "min_containers": vmin,
                  "scaledown_window_s": sd, "max_inputs": mxin,
                  "startup_timeout_s": 1200},
    }
    DEPLOY_CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def _run_deploy(run_id: str, admin_id: str, engines: list[str]) -> None:
    """Background worker: `modal deploy` the engine apps, record logs + endpoints."""
    url_re = re.compile(r"https://\S+\.modal\.run")
    log_parts: list[str] = []
    ok = True
    for engine in engines:
        app_path = ENGINE_APPS[engine]
        try:
            proc = subprocess.run(
                ["python", "-m", "modal", "deploy", str(app_path)],
                capture_output=True, text=True, timeout=1800, cwd=str(REPO_ROOT),
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            log_parts.append(f"$ modal deploy modal_app/{app_path.name}\n{out}")
            if proc.returncode != 0:
                ok = False
                break
            urls = url_re.findall(out)
            if urls:
                with db_conn() as conn, conn.cursor() as cur:
                    cur.execute(
                        f"update public.modal_settings set {engine}_endpoint = %s "
                        "where id = 1", (urls[0],),
                    )
        except Exception as e:  # noqa: BLE001 — record any failure in the run row
            log_parts.append(f"$ modal deploy modal_app/{app_path.name}\nERROR: {e}")
            ok = False
            break
    log = "\n\n".join(log_parts)[-50000:]
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "update public.deploy_runs set status = %s, log = %s, finished_at = now() "
            "where id = %s",
            ("succeeded" if ok else "failed", log, uuid.UUID(run_id)),
        )
        cur.execute("update public.modal_settings set pending_deploy = null where id = 1")
        _audit(conn, admin_id, "deploy.finish", "deploy_runs",
               {"run_id": run_id, "ok": ok})


@router.post("/deploy")
def trigger_deploy(admin: AdminDep, engines: str = Query("image,video")) -> dict:
    wanted = [e.strip() for e in engines.split(",") if e.strip() in ENGINE_APPS]
    if not wanted:
        raise HTTPException(422, "engines must be a comma list of image and/or video")
    with db_conn() as conn, conn.cursor() as cur:
        cfg = _write_deploy_config(conn)
        run_id = uuid.uuid4()
        cur.execute(
            "insert into public.deploy_runs (id, triggered_by, trigger_reason, "
            "config_snapshot) values (%s, %s, 'manual', %s) returning id, started_at",
            (run_id, admin.id, json.dumps(cfg)),
        )
        row = cur.fetchone()
        _audit(conn, admin.id, "deploy.trigger", ",".join(wanted),
               {"run_id": str(run_id)})
    threading.Thread(
        target=_run_deploy, args=(str(run_id), admin.id, wanted), daemon=True,
    ).start()
    return {"id": str(row[0]), "started_at": row[1].isoformat(),
            "engines": wanted, "config": cfg}


@router.get("/deploy")
def list_deploys(admin: AdminDep, limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select d.id, d.trigger_reason, d.status, d.started_at, d.finished_at, "
            "p.email as triggered_by from public.deploy_runs d "
            "left join public.profiles p on p.id = d.triggered_by "
            "order by d.started_at desc limit %s", (limit,),
        )
        return _rows_as_dicts(cur)


@router.get("/deploy/{run_id}")
def deploy_detail(run_id: uuid.UUID, admin: AdminDep) -> dict:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, trigger_reason, status, log, config_snapshot, started_at, "
            "finished_at from public.deploy_runs where id = %s", (run_id,),
        )
        rows = _rows_as_dicts(cur)
    if not rows:
        raise HTTPException(404, "deploy run not found")
    return rows[0]


# ------------------------------------------------------------------------ audit

@router.get("/audit")
def audit_log(
    admin: AdminDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select a.id, a.action, a.target, a.payload, a.created_at, "
            "p.email as admin_email from public.admin_audit_log a "
            "left join public.profiles p on p.id = a.admin_id "
            "order by a.created_at desc limit %s offset %s", (limit, offset),
        )
        return _rows_as_dicts(cur)


# ------------------------------------------------------------------- templates

_TEMPLATE_COLS = ("id, title, category, engine, mode, prompt, negative_prompt, "
                  "placeholders, example_image_path, active, sort_order, created_at")


def _template_rows(cur: psycopg.Cursor) -> list[dict]:
    rows = _rows_as_dicts(cur)
    for t in rows:
        if t.get("placeholders") is not None and not isinstance(t["placeholders"], list):
            t["placeholders"] = json.loads(t["placeholders"])
    return rows


@router.get("/templates")
def admin_list_templates(admin: AdminDep) -> list[dict]:
    """All templates including inactive ones, for the admin manager."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"select {_TEMPLATE_COLS} from public.prompt_templates "
            "order by sort_order, created_at"
        )
        return _template_rows(cur)


@router.post("/templates")
def admin_create_template(admin: AdminDep, body: TemplateBody) -> dict:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into public.prompt_templates "
            "(title, category, engine, mode, prompt, negative_prompt, "
            " placeholders, example_image_path, active, sort_order) "
            "values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s) "
            f"returning {_TEMPLATE_COLS}",
            (body.title, body.category, body.engine, body.mode, body.prompt,
             body.negative_prompt, json.dumps([p.model_dump() for p in body.placeholders]),
             body.example_image_path, body.active, body.sort_order),
        )
        row = _template_rows(cur)[0]
        _audit(conn, admin.id, "template.create", target=str(row["id"]),
               payload={"title": body.title})
    return row


@router.put("/templates/{template_id}")
def admin_update_template(template_id: str, admin: AdminDep,
                          body: TemplateBody) -> dict:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "update public.prompt_templates set title = %s, category = %s, "
            "engine = %s, mode = %s, prompt = %s, negative_prompt = %s, "
            "placeholders = %s::jsonb, example_image_path = %s, active = %s, "
            "sort_order = %s where id = %s "
            f"returning {_TEMPLATE_COLS}",
            (body.title, body.category, body.engine, body.mode, body.prompt,
             body.negative_prompt, json.dumps([p.model_dump() for p in body.placeholders]),
             body.example_image_path, body.active, body.sort_order, template_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "template not found")
        row = _template_rows(cur)[0]
        _audit(conn, admin.id, "template.update", target=template_id,
               payload={"title": body.title})
    return row


@router.delete("/templates/{template_id}")
def admin_delete_template(template_id: str, admin: AdminDep) -> dict:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from public.prompt_templates where id = %s returning title",
            (template_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "template not found")
        _audit(conn, admin.id, "template.delete", target=template_id,
               payload={"title": row[0]})
    return {"deleted": template_id, "title": row[0]}
