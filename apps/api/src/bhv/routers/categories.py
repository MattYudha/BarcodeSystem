from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from bhv.audit import audit
from bhv.db import execute, fetch_all, fetch_one
from bhv.deps import DB, Admin, CurrentUser
from bhv.errors import AppError
from bhv.schemas import CategoryIn, CategoryOut

router = APIRouter(prefix="/categories", tags=["catalog"])

_SELECT = """
SELECT c.id, c.name::text AS name, c.archived_at,
       (SELECT count(*) FROM products p WHERE p.category_id = c.id AND p.archived_at IS NULL)
         AS product_count
  FROM categories c
"""


def _out(row: Any) -> CategoryOut:
    return CategoryOut.model_validate(row._mapping)


async def _get(db: AsyncSession, cid: int) -> Any:
    row = await fetch_one(db, _SELECT + " WHERE c.id = :id", id=cid)
    if row is None:
        raise AppError("CATEGORY_NOT_FOUND")
    return row


@router.get("", response_model=list[CategoryOut])
async def list_categories(
    _: CurrentUser, db: DB, include_archived: bool = False
) -> list[CategoryOut]:
    where = "" if include_archived else " WHERE c.archived_at IS NULL"
    rows = await fetch_all(db, _SELECT + where + " ORDER BY c.name")
    return [_out(r) for r in rows]


@router.post("", response_model=CategoryOut, status_code=201)
async def create_category(body: CategoryIn, admin: Admin, db: DB) -> CategoryOut:
    row = await fetch_one(db, "INSERT INTO categories (name) VALUES (:n) RETURNING id", n=body.name)
    assert row is not None
    await audit(db, admin, "category.create", "category", row.id, after={"name": body.name})
    out = _out(await _get(db, row.id))
    await db.commit()
    return out


@router.patch("/{category_id}", response_model=CategoryOut)
async def rename_category(category_id: int, body: CategoryIn, admin: Admin, db: DB) -> CategoryOut:
    before = await _get(db, category_id)
    await fetch_all(db, "UPDATE categories SET name = :n WHERE id = :id RETURNING id",
                    n=body.name, id=category_id)  # fmt: skip
    await audit(db, admin, "category.rename", "category", category_id,
                before={"name": before.name}, after={"name": body.name})  # fmt: skip
    out = _out(await _get(db, category_id))
    await db.commit()
    return out


async def _set_archived(
    db: AsyncSession, admin: Any, category_id: int, archived: bool
) -> CategoryOut:
    await _get(db, category_id)
    expr = "coalesce(archived_at, now())" if archived else "NULL"
    await execute(db, f"UPDATE categories SET archived_at = {expr} WHERE id = :id", id=category_id)
    await audit(db, admin, "category.archive" if archived else "category.unarchive",
                "category", category_id)  # fmt: skip
    out = _out(await _get(db, category_id))
    await db.commit()
    return out


@router.post("/{category_id}/archive", response_model=CategoryOut)
async def archive_category(category_id: int, admin: Admin, db: DB) -> CategoryOut:
    return await _set_archived(db, admin, category_id, True)


@router.post("/{category_id}/unarchive", response_model=CategoryOut)
async def unarchive_category(category_id: int, admin: Admin, db: DB) -> CategoryOut:
    return await _set_archived(db, admin, category_id, False)
