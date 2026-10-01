"""Public studio configuration + pricing estimate endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from app.core.db import db_conn
from app.dependencies import UserDep

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/studio")
def studio_config() -> dict:
    """Everything the Studio UI needs to render its composer."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select site_name, maintenance_mode, "
            "default_negative_prompt_image, default_negative_prompt_video "
            "from public.app_settings where id = 1"
        )
        site, maint, neg_img, neg_vid = cur.fetchone()
        cur.execute(
            "select engine, params from public.engine_configs where enabled"
        )
        engines = {e: (p if isinstance(p, dict) else json.loads(p))
                   for e, p in cur.fetchall()}
        cur.execute(
            "select engine, base_credits, credits_per_megapixel, "
            "credits_per_ref_image, credits_per_video_second "
            "from public.pricing_rules where active"
        )
        pricing = {
            e: {"base_credits": b, "per_megapixel": float(m),
                "per_ref_image": r, "per_video_second": float(v)}
            for e, b, m, r, v in cur.fetchall()
        }
    return {
        "site_name": site,
        "maintenance_mode": maint,
        "default_negative_prompts": {"image": neg_img, "video": neg_vid},
        "engines": engines,
        "pricing": pricing,
    }


@router.get("/estimate")
def estimate(
    user: UserDep,
    engine: str = Query(pattern="^(image|video)$"),
    width: int = 1024,
    height: int = 1024,
    duration_s: int = 5,
    ref_count: int = 0,
) -> dict:
    params = {"width": width, "height": height}
    if engine == "video":
        params["duration_s"] = duration_s
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("select public.compute_generation_credits(%s, %s, %s)",
                    (engine, json.dumps(params), ref_count))
        credits = cur.fetchone()[0]
    return {"credits": credits}
