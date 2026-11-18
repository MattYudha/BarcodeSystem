"""Dependency autentikasi & otorisasi. Semua hak akses dicek di server."""

import ipaddress
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from bhv.config import get_settings
from bhv.db import execute, fetch_one, get_db
from bhv.errors import AppError
from bhv.security import token_digest

DB = Annotated[AsyncSession, Depends(get_db)]
Role = Literal["admin", "staff"]

# last_seen_at hanya diperbarui jika lebih tua dari ini (hemat write).
_TOUCH_INTERVAL = timedelta(seconds=60)


@dataclass(frozen=True)
class Principal:
    user_id: int
    name: str
    email: str
    role: Role
    session_id: str
    must_change_password: bool
    ip: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def client_ip(request: Request) -> str | None:
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:  # mis. "testclient"
        return None


async def _load_principal(request: Request, db: AsyncSession) -> Principal:
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise AppError("UNAUTHENTICATED")

    row = await fetch_one(
        db,
        """
        SELECT s.id::text AS sid, s.last_seen_at, s.expires_at, now() AS now,
               u.id AS uid, u.name, u.email::text AS email, u.role::text AS role,
               u.is_active, u.must_change_password
          FROM sessions s JOIN users u ON u.id = s.user_id
         WHERE s.token_hash = :h AND s.revoked_at IS NULL
        """,
        h=token_digest(token),
    )
    if row is None or not row.is_active:
        raise AppError("UNAUTHENTICATED")

    idle_limit = row.last_seen_at + timedelta(minutes=settings.session_idle_minutes)
    if row.now >= row.expires_at or row.now >= idle_limit:
        await execute(db, "UPDATE sessions SET revoked_at = now() WHERE id = :sid", sid=row.sid)
        await db.commit()
        raise AppError("SESSION_EXPIRED")

    if row.now - row.last_seen_at >= _TOUCH_INTERVAL:
        await execute(db, "UPDATE sessions SET last_seen_at = now() WHERE id = :sid", sid=row.sid)
        await db.commit()

    return Principal(
        user_id=row.uid,
        name=row.name,
        email=row.email,
        role=row.role,
        session_id=row.sid,
        must_change_password=row.must_change_password,
        ip=client_ip(request),
    )


async def current_principal_any(request: Request, db: DB) -> Principal:
    """User login, termasuk yang masih wajib ganti password (untuk /auth/*)."""
    return await _load_principal(request, db)


async def current_principal(request: Request, db: DB) -> Principal:
    p = await _load_principal(request, db)
    if p.must_change_password:
        raise AppError("PASSWORD_CHANGE_REQUIRED")
    return p


async def require_admin(p: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if not p.is_admin:
        raise AppError("FORBIDDEN")
    return p


AnyUser = Annotated[Principal, Depends(current_principal_any)]
CurrentUser = Annotated[Principal, Depends(current_principal)]
Admin = Annotated[Principal, Depends(require_admin)]
