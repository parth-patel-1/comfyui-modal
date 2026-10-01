"""Prompt template gallery ("Discover"): list templates + serve example images.

Templates are managed by admins (see admin router); these endpoints are read-
only for any signed-in user. The example image lives in the private
`references` bucket, so it is proxied through the backend with service auth.
"""

from __future__ import annotations

import json
import uuid

import psycopg
from fastapi import APIRouter, HTTPException, Response

from app.core.db import db_conn
from app.dependencies import UserDep
from app.services import storage

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _fetch_template(cur: psycopg.Cursor, template_id: str) -> dict | None:
    cur.execute(
        "select id, title, category, engine, mode, prompt, negative_prompt, "
        "placeholders, example_image_path, active, sort_order, created_at "
        "from public.prompt_templates where id = %s",
        (template_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    t = dict(zip(cols, row))
    t["id"] = str(t["id"])
    if t["placeholders"] is not None and not isinstance(t["placeholders"], list):
        t["placeholders"] = json.loads(t["placeholders"])
    return t


@router.get("")
def list_templates(user: UserDep) -> list[dict]:
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, title, category, engine, mode, prompt, negative_prompt, "
            "placeholders, example_image_path, active, sort_order, created_at "
            "from public.prompt_templates where active "
            "order by sort_order, created_at"
        )
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            t = dict(zip(cols, r))
            t["id"] = str(t["id"])
            if t["placeholders"] is not None and not isinstance(t["placeholders"], list):
                t["placeholders"] = json.loads(t["placeholders"])
            out.append(t)
    return out


@router.get("/{template_id}/image")
def template_image(template_id: str, user: UserDep) -> Response:
    """Proxy the example image (private bucket) with service credentials."""
    try:
        tid = uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(404, "template not found")
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select example_image_path from public.prompt_templates "
            "where id = %s and active",
            (tid,),
        )
        row = cur.fetchone()
    if row is None or not row[0]:
        raise HTTPException(404, "template image not found")
    path: str = row[0]
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else "png"
    media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
             "webp": "image/webp"}.get(ext, "image/png")
    try:
        data = storage.download("references", path)
    except storage.StorageError:
        raise HTTPException(404, "template image not found")
    return Response(
        content=data,
        media_type=media,
        headers={"Cache-Control": "private, max-age=3600"},
    )
