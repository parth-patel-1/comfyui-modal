"""FastAPI dependencies: bearer-token auth + role checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import psycopg
from fastapi import Depends, HTTPException, Request

from app.core.db import db_conn
from app.core.security import AuthError, verify_token


@dataclass
class CurrentUser:
    id: str
    email: str
    role: str
    status: str


def get_current_user(request: Request) -> CurrentUser:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = auth[7:].strip()
    try:
        user = verify_token(token)
    except AuthError as e:
        raise HTTPException(401, str(e)) from e

    uid = user.get("id")
    if not uid:
        raise HTTPException(401, "token has no subject")

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select role, status from public.profiles where id = %s", (uid,)
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(403, "profile not provisioned")
    role, status = row
    if status != "active":
        raise HTTPException(403, "account suspended")
    return CurrentUser(id=uid, email=user.get("email", ""), role=role, status=status)


def require_admin(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(403, "admin only")
    return user


DbConn = Annotated[psycopg.Connection, Depends(db_conn)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
AdminDep = Annotated[CurrentUser, Depends(require_admin)]
