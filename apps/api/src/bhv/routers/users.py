from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from bhv.audit import audit
from bhv.db import execute, fetch_all, fetch_one
from bhv.deps import DB, Admin
from bhv.errors import AppError
from bhv.schemas import (
    TempPasswordOut,
    UserCreatedOut,
    UserCreateIn,
    UserOut,
    UserPatchIn,
)
from bhv.security import generate_temp_password, hash_password

router = APIRouter(prefix="/users", tags=["users"])

_COLS = """id, name, email::text AS email, role::text AS role, is_active, must_change_password,
           last_login_at, created_at"""


def _out(row: Any) -> UserOut:
    return UserOut.model_validate(row._mapping)


async def _get(db: AsyncSession, user_id: int, lock: bool = False) -> Any:
    row = await fetch_one(
        db, f"SELECT {_COLS} FROM users WHERE id = :id {'FOR UPDATE' if lock else ''}", id=user_id
    )
    if row is None:
        raise AppError("USER_NOT_FOUND")
    return row


async def _revoke_sessions(db: AsyncSession, user_id: int) -> None:
    await execute(
        db,
        "UPDATE sessions SET revoked_at = now() WHERE user_id = :id AND revoked_at IS NULL",
        id=user_id,
    )


@router.get("", response_model=list[UserOut])
async def list_users(_: Admin, db: DB) -> list[UserOut]:
    rows = await fetch_all(db, f"SELECT {_COLS} FROM users ORDER BY is_active DESC, name, id")
    return [_out(r) for r in rows]


@router.post("", response_model=UserCreatedOut, status_code=201)
async def create_user(body: UserCreateIn, admin: Admin, db: DB) -> UserCreatedOut:
    temp = None if body.password else generate_temp_password()
    row = await fetch_one(
        db,
        f"""
        INSERT INTO users (name, email, password_hash, role, must_change_password, created_by)
        VALUES (:name, :email, :hash, CAST(:role AS user_role), :must, :by)
        RETURNING {_COLS}
        """,
        name=body.name,
        email=body.email,
        hash=hash_password(body.password or temp or ""),
        role=body.role,
        must=temp is not None,
        by=admin.user_id,
    )
    assert row is not None
    await audit(db, admin, "user.create", "user", row.id,
                after={"name": body.name, "email": body.email, "role": body.role})  # fmt: skip
    await db.commit()
    return UserCreatedOut(**_out(row).model_dump(), temp_password=temp)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserPatchIn, admin: Admin, db: DB) -> UserOut:
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if user_id == admin.user_id and ("role" in changes or "is_active" in changes):
        raise AppError("CANNOT_MODIFY_SELF")

    # Kunci semua admin aktif dulu (urutan id) -> dua admin tidak bisa saling menurunkan
    # bersamaan sampai admin habis.
    admins = await fetch_all(
        db, "SELECT id FROM users WHERE role = 'admin' AND is_active ORDER BY id FOR UPDATE"
    )
    before = await _get(db, user_id, lock=True)
    loses_admin = (
        before.role == "admin"
        and before.is_active
        and (changes.get("role") == "staff" or changes.get("is_active") is False)
    )
    if loses_admin and len(admins) <= 1:
        raise AppError("LAST_ADMIN")

    if changes:
        sets = []
        if "name" in changes:
            sets.append("name = :name")
        if "role" in changes:
            sets.append("role = CAST(:role AS user_role)")
        if "is_active" in changes:
            sets.append("is_active = :is_active")
        await execute(
            db, f"UPDATE users SET {', '.join(sets)} WHERE id = :id", id=user_id, **changes
        )
        if changes.get("is_active") is False:
            await _revoke_sessions(db, user_id)
        await audit(
            db, admin, "user.update", "user", user_id,
            before={k: getattr(before, k) for k in changes}, after=changes,
        )  # fmt: skip
    after = await _get(db, user_id)
    await db.commit()
    return _out(after)


@router.post("/{user_id}/reset-password", response_model=TempPasswordOut)
async def reset_password(user_id: int, admin: Admin, db: DB) -> TempPasswordOut:
    if user_id == admin.user_id:
        raise AppError(
            "CANNOT_MODIFY_SELF", message="Gunakan menu Ganti Password untuk akun sendiri."
        )
    await _get(db, user_id, lock=True)
    temp = generate_temp_password()
    await execute(
        db,
        """UPDATE users SET password_hash = :h, must_change_password = TRUE,
                            password_changed_at = now() WHERE id = :id""",
        h=hash_password(temp),
        id=user_id,
    )
    await _revoke_sessions(db, user_id)
    await audit(db, admin, "user.reset_password", "user", user_id)
    await db.commit()
    return TempPasswordOut(temp_password=temp)
