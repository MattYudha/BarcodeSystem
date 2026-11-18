"""F-13 stock opname (khusus admin).

Alur: buat draft -> hitung fisik (ketik jumlah / scan barcode +1) -> finalize.
Saat finalize, selisih dihitung terhadap stok SAAT ITU (baris varian dikunci), lalu dicatat sebagai
transaksi ADJUST dalam satu transaksi DB. Hanya varian yang dihitung yang disesuaikan.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy.ext.asyncio import AsyncSession

from bhv.audit import audit
from bhv.db import execute, fetch_all, fetch_one
from bhv.deps import DB, Admin
from bhv.errors import AppError
from bhv.schemas_stock import (
    OpnameCreateIn,
    OpnameItemOut,
    OpnameItemsIn,
    OpnameOut,
    OpnameScanIn,
    OpnameStatus,
    UserBrief,
)
from bhv.services.movements import Line, insert_group
from bhv.services.queries import variant_brief

router = APIRouter(prefix="/opnames", tags=["opname"])

_HEAD = """
SELECT o.id, o.code, o.status::text AS status, o.note, o.created_at, o.finalized_at,
       o.cancelled_at, cu.id AS created_by_id, cu.name AS created_by_name,
       fu.id AS finalized_by_id, fu.name AS finalized_by_name,
       (SELECT count(*) FROM stock_opname_items i WHERE i.opname_id = o.id) AS item_count
  FROM stock_opnames o
  JOIN users cu ON cu.id = o.created_by
  LEFT JOIN users fu ON fu.id = o.finalized_by
"""

_ITEMS = """
SELECT i.variant_id, i.counted_qty, i.counted_at, u.id AS counted_by_id, u.name AS counted_by_name,
       CASE WHEN o.status = 'finalized' THEN i.system_qty ELSE vs.stock END AS current_stock,
       vs.barcode, vs.size, vs.color, vs.product_id, vs.product_code, vs.product_name,
       vs.category_name
  FROM stock_opname_items i
  JOIN stock_opnames o ON o.id = i.opname_id
  JOIN v_variant_stock vs ON vs.variant_id = i.variant_id
  JOIN users u ON u.id = i.counted_by
 WHERE i.opname_id = :id
"""


def _item_out(r: Any) -> OpnameItemOut:
    return OpnameItemOut(
        variant=variant_brief(r),
        counted_qty=r.counted_qty,
        current_stock=r.current_stock,
        diff=r.counted_qty - r.current_stock,
        counted_by=UserBrief(id=r.counted_by_id, name=r.counted_by_name),
        counted_at=r.counted_at,
    )


async def _get(db: AsyncSession, opname_id: int, with_items: bool = True) -> OpnameOut:
    h = await fetch_one(db, _HEAD + " WHERE o.id = :id", id=opname_id)
    if h is None:
        raise AppError("OPNAME_NOT_FOUND")
    items: list[OpnameItemOut] = []
    if with_items:
        rows = await fetch_all(db, _ITEMS + " ORDER BY vs.product_name, i.variant_id", id=opname_id)
        items = [_item_out(r) for r in rows]
    return OpnameOut(
        id=h.id,
        code=h.code,
        status=h.status,
        note=h.note,
        created_by=UserBrief(id=h.created_by_id, name=h.created_by_name),
        created_at=h.created_at,
        finalized_by=(
            UserBrief(id=h.finalized_by_id, name=h.finalized_by_name) if h.finalized_by_id else None
        ),
        finalized_at=h.finalized_at,
        cancelled_at=h.cancelled_at,
        item_count=h.item_count,
        diff_count=sum(1 for i in items if i.diff != 0),
        items=items,
    )


async def _require_draft(db: AsyncSession, opname_id: int, lock: bool = False) -> Any:
    row = await fetch_one(
        db,
        "SELECT id, code, status::text AS status FROM stock_opnames WHERE id = :id"
        + (" FOR UPDATE" if lock else ""),
        id=opname_id,
    )
    if row is None:
        raise AppError("OPNAME_NOT_FOUND")
    if row.status != "draft":
        raise AppError("OPNAME_CLOSED", {"status": row.status})
    return row


@router.get("", response_model=list[OpnameOut])
async def list_opnames(
    _: Admin, db: DB, status: OpnameStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[OpnameOut]:  # fmt: skip
    params: dict[str, Any] = {"lim": limit}
    where = ""
    if status:
        where, params["st"] = " WHERE status::text = :st", status
    rows = await fetch_all(
        db, f"SELECT id FROM stock_opnames{where} ORDER BY id DESC LIMIT :lim", **params
    )
    return [await _get(db, r.id, with_items=False) for r in rows]


@router.post("", response_model=OpnameOut, status_code=201)
async def create_opname(body: OpnameCreateIn, admin: Admin, db: DB) -> OpnameOut:
    row = await fetch_one(
        db,
        "INSERT INTO stock_opnames (note, created_by) VALUES (:note, :by) RETURNING id",
        note=body.note,
        by=admin.user_id,
    )
    assert row is not None
    await audit(db, admin, "opname.create", "opname", row.id)
    out = await _get(db, row.id)
    await db.commit()
    return out


@router.get("/{opname_id}", response_model=OpnameOut)
async def get_opname(opname_id: int, _: Admin, db: DB) -> OpnameOut:
    return await _get(db, opname_id)


async def _require_variants(db: AsyncSession, ids: list[int]) -> None:
    found = {r.id for r in await fetch_all(
        db, "SELECT id FROM product_variants WHERE id = ANY(:ids)", ids=ids)}  # fmt: skip
    missing = sorted(set(ids) - found)
    if missing:
        raise AppError("VARIANT_NOT_FOUND", {"variant_ids": missing})


@router.put("/{opname_id}/items", response_model=OpnameOut)
async def set_counts(opname_id: int, body: OpnameItemsIn, admin: Admin, db: DB) -> OpnameOut:
    """Set jumlah fisik (absolut) untuk satu/lebih varian."""
    await _require_draft(db, opname_id)
    counts: dict[int, int] = {}
    for it in body.items:  # varian sama dikirim dua kali -> nilai terakhir dipakai
        counts[it.variant_id] = it.counted_qty
    await _require_variants(db, list(counts))
    for vid, qty in sorted(counts.items()):
        await execute(
            db,
            """INSERT INTO stock_opname_items (opname_id, variant_id, counted_qty, counted_by)
               VALUES (:o, :v, :q, :u)
               ON CONFLICT (opname_id, variant_id) DO UPDATE
                 SET counted_qty = EXCLUDED.counted_qty, counted_by = EXCLUDED.counted_by,
                     counted_at = now()""",
            o=opname_id,
            v=vid,
            q=qty,
            u=admin.user_id,
        )
    out = await _get(db, opname_id)
    await db.commit()
    return out


@router.post("/{opname_id}/scan", response_model=OpnameItemOut)
async def scan_count(opname_id: int, body: OpnameScanIn, admin: Admin, db: DB) -> OpnameItemOut:
    """Mode hitung dengan scanner: setiap scan menambah jumlah fisik (default +1)."""
    await _require_draft(db, opname_id)
    code = body.barcode.strip().upper()
    vid = await fetch_one(db, "SELECT id FROM product_variants WHERE barcode = :b", b=code)
    if vid is None:
        raise AppError("VARIANT_NOT_FOUND", {"barcode": code})
    await execute(
        db,
        """INSERT INTO stock_opname_items (opname_id, variant_id, counted_qty, counted_by)
           VALUES (:o, :v, :q, :u)
           ON CONFLICT (opname_id, variant_id) DO UPDATE
             SET counted_qty = stock_opname_items.counted_qty + EXCLUDED.counted_qty,
                 counted_by = EXCLUDED.counted_by, counted_at = now()""",
        o=opname_id,
        v=vid.id,
        q=body.increment,
        u=admin.user_id,
    )
    row = await fetch_one(db, _ITEMS + " AND i.variant_id = :v", id=opname_id, v=vid.id)
    await db.commit()
    return _item_out(row)


@router.delete("/{opname_id}/items/{variant_id}", status_code=204)
async def remove_count(opname_id: int, variant_id: int, _: Admin, db: DB) -> None:
    await _require_draft(db, opname_id)
    n = await execute(
        db,
        "DELETE FROM stock_opname_items WHERE opname_id = :o AND variant_id = :v",
        o=opname_id,
        v=variant_id,
    )
    if n == 0:
        raise AppError("OPNAME_ITEM_NOT_FOUND")
    await db.commit()


@router.post("/{opname_id}/finalize", response_model=OpnameOut)
async def finalize_opname(opname_id: int, admin: Admin, db: DB) -> OpnameOut:
    head = await fetch_one(
        db,
        "SELECT id, code, status::text AS status FROM stock_opnames WHERE id = :id FOR UPDATE",
        id=opname_id,
    )
    if head is None:
        raise AppError("OPNAME_NOT_FOUND")
    if head.status == "finalized":  # klik ganda: kembalikan hasil yang sudah ada
        return await _get(db, opname_id)
    if head.status != "draft":
        raise AppError("OPNAME_CLOSED", {"status": head.status})

    items = await fetch_all(
        db,
        "SELECT variant_id, counted_qty FROM stock_opname_items WHERE opname_id = :id"
        " ORDER BY variant_id",
        id=opname_id,
    )
    if not items:
        raise AppError("OPNAME_EMPTY")
    # Kunci varian (urut id) agar stok tidak berubah antara hitung selisih & penyesuaian.
    stocks = {
        r.id: r.stock
        for r in await fetch_all(
            db,
            "SELECT id, stock FROM product_variants WHERE id = ANY(:ids) ORDER BY id FOR UPDATE",
            ids=[i.variant_id for i in items],
        )
    }
    lines: list[Line] = []
    for it in items:
        system_qty = stocks[it.variant_id]
        diff = it.counted_qty - system_qty
        await execute(
            db,
            """UPDATE stock_opname_items SET system_qty = :s, diff = :d
                WHERE opname_id = :o AND variant_id = :v""",
            s=system_qty,
            d=diff,
            o=opname_id,
            v=it.variant_id,
        )
        if diff != 0:
            lines.append(
                Line(
                    variant_id=it.variant_id,
                    qty=diff,
                    note=f"Stock opname {head.code}",
                    source="opname",
                    opname_id=opname_id,
                )
            )
    if lines:
        await insert_group(db, admin, "ADJUST", lines)
    await execute(
        db,
        """UPDATE stock_opnames SET status = 'finalized', finalized_at = now(), finalized_by = :u
            WHERE id = :id""",
        u=admin.user_id,
        id=opname_id,
    )
    await audit(db, admin, "opname.finalize", "opname", opname_id,
                after={"items": len(items), "adjusted": len(lines)})  # fmt: skip
    out = await _get(db, opname_id)
    await db.commit()
    return out


@router.post("/{opname_id}/cancel", response_model=OpnameOut)
async def cancel_opname(opname_id: int, admin: Admin, db: DB) -> OpnameOut:
    head = await fetch_one(
        db, "SELECT status::text AS status FROM stock_opnames WHERE id = :id FOR UPDATE",
        id=opname_id,
    )  # fmt: skip
    if head is None:
        raise AppError("OPNAME_NOT_FOUND")
    if head.status == "cancelled":
        return await _get(db, opname_id)
    if head.status != "draft":
        raise AppError("OPNAME_CLOSED", {"status": head.status})
    await execute(
        db,
        "UPDATE stock_opnames SET status = 'cancelled', cancelled_at = now() WHERE id = :id",
        id=opname_id,
    )
    await audit(db, admin, "opname.cancel", "opname", opname_id)
    out = await _get(db, opname_id)
    await db.commit()
    return out
