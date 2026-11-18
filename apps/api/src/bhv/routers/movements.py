"""Transaksi stok: scan masuk/keluar (keranjang), penyesuaian, pembatalan, riwayat, kartu stok.

Idempotensi: client membuat UUID per submit (header Idempotency-Key). Submit ulang dengan kunci
& isi yang sama mengembalikan hasil lama (replayed=true) tanpa transaksi baru.
"""

import uuid
from datetime import date, timedelta
from typing import Annotated, Any

import psycopg.errors as pg
from fastapi import APIRouter, Header, Query
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bhv.db import fetch_all, fetch_one, fetch_val
from bhv.deps import DB, Admin, CurrentUser, Principal
from bhv.errors import AppError, from_db_error
from bhv.routers.products import like
from bhv.schemas import Page
from bhv.schemas_stock import (
    AdjustIn,
    MovementCreateIn,
    MovementGroupOut,
    MovementOut,
    MovementType,
    ReverseIn,
    StockCardOut,
)
from bhv.services.movements import Line, insert_group, request_hash
from bhv.services.queries import MOVEMENT_SELECT, can_reverse, movement_out, variant_brief
from bhv.timeutil import PeriodError, resolve_period, today_wib, wib_midnight_utc

router = APIRouter(tags=["stock"])

IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]
STOCK_CARD_LIMIT = 2000


def _parse_key(raw: str | None, required: bool = True) -> uuid.UUID | None:
    if not raw:
        if required:
            raise AppError("IDEMPOTENCY_KEY_REQUIRED")
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise AppError("IDEMPOTENCY_KEY_REQUIRED") from None


async def _group_movements(
    db: AsyncSession, gid: uuid.UUID, viewer: Principal
) -> list[MovementOut]:
    rows = await fetch_all(db, MOVEMENT_SELECT + " WHERE m.group_id = :gid ORDER BY m.id", gid=gid)
    return [movement_out(r, viewer) for r in rows]


async def _replay(
    db: AsyncSession, key: uuid.UUID, req_hash: str, p: Principal
) -> MovementGroupOut | None:
    g = await fetch_one(
        db,
        "SELECT kind::text AS kind, request_hash, user_id FROM movement_groups WHERE id = :id",
        id=key,
    )
    if g is None:
        return None
    if g.user_id != p.user_id or g.request_hash != req_hash:
        raise AppError("IDEMPOTENCY_MISMATCH")
    return MovementGroupOut(
        group_id=str(key),
        type=g.kind,
        replayed=True,
        movements=await _group_movements(db, key, p),
    )


async def _enrich_db_error(db: AsyncSession, exc: DBAPIError) -> AppError | None:
    err = from_db_error(exc)
    if err is None or err.code not in ("INSUFFICIENT_STOCK", "VARIANT_ARCHIVED"):
        return err
    vid = err.details.get("variant_id")
    row = await fetch_one(
        db,
        "SELECT barcode, product_name, size, color FROM v_variant_stock WHERE variant_id = :id",
        id=vid,
    )
    if row is None:
        return err
    label = f"{row.product_name} ({row.size}{', ' + row.color if row.color else ''})"
    err.details["barcode"] = row.barcode
    if err.code == "INSUFFICIENT_STOCK":
        err.message = (
            f"Stok {label} tidak cukup: tersedia {err.details.get('available')}, "
            f"diminta {err.details.get('requested')}."
        )
    else:
        err.message = f"{label} sudah diarsipkan dan tidak bisa dipakai transaksi."
    return err


def _is_group_key_conflict(exc: DBAPIError) -> bool:
    return isinstance(exc.orig, pg.UniqueViolation) and (
        exc.orig.diag.constraint_name == "movement_groups_pkey"
    )


async def _write_group(
    db: AsyncSession,
    p: Principal,
    kind: MovementType,
    lines: list[Line],
    key: uuid.UUID | None,
    req_hash: str,
) -> MovementGroupOut:
    """Simpan satu grup transaksi secara atomik + tangani idempotensi & race submit ganda."""
    if key is not None:
        replay = await _replay(db, key, req_hash, p)
        if replay:
            return replay
    try:
        gid, _ = await insert_group(db, p, kind, lines, group_id=key, req_hash=req_hash)
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if key is not None and _is_group_key_conflict(exc):
            # Submit ganda bersamaan: request lain sudah commit dengan kunci yang sama.
            replay = await _replay(db, key, req_hash, p)
            if replay:
                return replay
        err = await _enrich_db_error(db, exc)
        if err is None:
            raise
        raise err from exc
    return MovementGroupOut(
        group_id=str(gid), type=kind, replayed=False, movements=await _group_movements(db, gid, p)
    )


@router.post("/movements", response_model=MovementGroupOut)
async def create_movements(
    body: MovementCreateIn, p: CurrentUser, db: DB, idempotency_key: IdemKey = None
) -> MovementGroupOut:
    """Barang masuk (IN) / keluar (OUT). Semua baris tersimpan atau tidak sama sekali."""
    key = _parse_key(idempotency_key)
    sign = 1 if body.type == "IN" else -1
    lines = [
        Line(
            variant_id=ln.variant_id,
            qty=sign * ln.qty,
            reason=ln.reason,
            production_date=ln.production_date,
            batch_code=ln.batch_code,
            note=ln.note,
            source=body.source,
        )
        for ln in body.lines
    ]
    h = request_hash({"kind": body.type, **body.model_dump(mode="json")})
    return await _write_group(db, p, body.type, lines, key, h)


@router.post("/movements/adjust", response_model=MovementGroupOut)
async def adjust_stock(
    body: AdjustIn, admin: Admin, db: DB, idempotency_key: IdemKey = None
) -> MovementGroupOut:
    """Penyesuaian stok manual (khusus admin, wajib catatan)."""
    key = _parse_key(idempotency_key)
    lines = [Line(variant_id=ln.variant_id, qty=ln.qty, note=ln.note) for ln in body.lines]
    h = request_hash({"kind": "ADJUST", **body.model_dump(mode="json")})
    return await _write_group(db, admin, "ADJUST", lines, key, h)


@router.post("/movements/{movement_id}/reverse", response_model=MovementOut)
async def reverse_movement(
    movement_id: int, body: ReverseIn, p: CurrentUser, db: DB, idempotency_key: IdemKey = None
) -> MovementOut:
    key = _parse_key(idempotency_key, required=False)
    row = await fetch_one(db, MOVEMENT_SELECT + " WHERE m.id = :id", id=movement_id)
    if row is None:
        raise AppError("MOVEMENT_NOT_FOUND")
    h = request_hash({"kind": "REVERSAL", "of": movement_id, **body.model_dump(mode="json")})
    if key is not None and (replay := await _replay(db, key, h, p)):
        return replay.movements[0]
    if row.type == "REVERSAL":
        raise AppError("CANNOT_REVERSE_REVERSAL")
    if row.reversed_by is not None:
        raise AppError("ALREADY_REVERSED")
    if not can_reverse(
        p, type_=row.type, user_id=row.user_id, created_at=row.created_at, reversed_by=None
    ):
        raise AppError("REVERSAL_NOT_ALLOWED")
    line = Line(
        variant_id=row.variant_id,
        qty=-row.qty,
        note=body.note,
        reversal_of=movement_id,
        source="manual",
    )
    group = await _write_group(db, p, "REVERSAL", [line], key, h)
    return group.movements[0]


@router.get("/movements", response_model=Page[MovementOut])
async def list_movements(
    p: CurrentUser,
    db: DB,
    date_from: date | None = None,
    date_to: date | None = None,
    type: Annotated[list[MovementType] | None, Query()] = None,  # noqa: A002
    variant_id: int | None = None,
    product_id: int | None = None,
    category_id: int | None = None,
    user_id: int | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[MovementOut]:
    """Admin melihat semua; staf hanya transaksinya sendiri."""
    where, params = movement_filters(
        date_from=date_from, date_to=date_to, types=type, variant_id=variant_id,
        product_id=product_id, category_id=category_id,
        user_id=user_id if p.is_admin else p.user_id, q=q,
    )  # fmt: skip
    total = await fetch_val(
        db,
        "SELECT count(*) FROM stock_movements m JOIN product_variants pv ON pv.id = m.variant_id"
        " JOIN products p ON p.id = pv.product_id" + where,
        **params,
    )
    rows = await fetch_all(
        db,
        MOVEMENT_SELECT + where + " ORDER BY m.id DESC LIMIT :limit OFFSET :offset",
        **params,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return Page[MovementOut](
        items=[movement_out(r, p) for r in rows], total=total, page=page, page_size=page_size
    )


def movement_filters(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    types: list[MovementType] | None = None,
    variant_id: int | None = None,
    product_id: int | None = None,
    category_id: int | None = None,
    user_id: int | None = None,
    q: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """WHERE untuk alias m (stock_movements), pv (variant), p (product). Tanggal = WIB inklusif."""
    where: list[str] = []
    params: dict[str, Any] = {}
    if date_from:
        where.append("m.created_at >= :start")
        params["start"] = wib_midnight_utc(date_from)
    if date_to:
        where.append("m.created_at < :end")
        params["end"] = wib_midnight_utc(date_to + timedelta(days=1))
    if types:
        where.append("m.type::text = ANY(:types)")
        params["types"] = list(types)
    if variant_id is not None:
        where.append("m.variant_id = :vid")
        params["vid"] = variant_id
    if product_id is not None:
        where.append("pv.product_id = :pid")
        params["pid"] = product_id
    if category_id is not None:
        where.append("p.category_id = :cat")
        params["cat"] = category_id
    if user_id is not None:
        where.append("m.user_id = :uid")
        params["uid"] = user_id
    if q and q.strip():
        where.append("(p.name ILIKE :q OR p.code ILIKE :q OR pv.barcode ILIKE :q)")
        params["q"] = like(q.strip())
    return (" WHERE " + " AND ".join(where)) if where else "", params


@router.get("/movements/{movement_id}", response_model=MovementOut)
async def get_movement(movement_id: int, p: CurrentUser, db: DB) -> MovementOut:
    row = await fetch_one(db, MOVEMENT_SELECT + " WHERE m.id = :id", id=movement_id)
    if row is None or (not p.is_admin and row.user_id != p.user_id):
        raise AppError("MOVEMENT_NOT_FOUND")
    return movement_out(row, p)


# ----------------------------------------------------------------------------- kartu stok


@router.get("/variants/{variant_id}/stock-card", response_model=StockCardOut)
async def stock_card(
    variant_id: int,
    p: CurrentUser,
    db: DB,
    date_from: date | None = None,
    date_to: date | None = None,
) -> StockCardOut:
    """F-16 riwayat lengkap per varian: saldo awal, transaksi (urut waktu), saldo akhir."""
    today = today_wib()
    try:
        period = resolve_period(
            "range", date_from=date_from or today - timedelta(days=29), date_to=date_to or today
        )
    except PeriodError as e:
        raise AppError("PERIOD_INVALID", message=str(e)) from None
    v = await fetch_one(
        db,
        """SELECT vs.variant_id, vs.barcode, vs.size, vs.color, vs.product_id, vs.product_code,
                  vs.product_name, vs.category_name, vs.stock
             FROM v_variant_stock vs WHERE vs.variant_id = :id""",
        id=variant_id,
    )
    if v is None:
        raise AppError("VARIANT_NOT_FOUND")
    start, end = period.start_utc, period.end_utc

    async def balance_before(t: Any) -> int:
        val = await fetch_val(
            db,
            """SELECT balance_after FROM stock_movements
                WHERE variant_id = :v AND created_at < :t
                ORDER BY created_at DESC, id DESC LIMIT 1""",
            v=variant_id,
            t=t,
        )
        return int(val or 0)

    totals = await fetch_one(
        db,
        """SELECT coalesce(sum(qty) FILTER (WHERE type = 'IN'), 0) AS qin,
                  coalesce(-sum(qty) FILTER (WHERE type = 'OUT'), 0) AS qout,
                  coalesce(sum(qty) FILTER (WHERE type = 'ADJUST'), 0) AS qadj,
                  coalesce(sum(qty) FILTER (WHERE type = 'REVERSAL'), 0) AS qrev,
                  count(*) AS n
             FROM stock_movements
            WHERE variant_id = :v AND created_at >= :s AND created_at < :e""",
        v=variant_id,
        s=start,
        e=end,
    )
    assert totals is not None
    rows = await fetch_all(
        db,
        MOVEMENT_SELECT + " WHERE m.variant_id = :v AND m.created_at >= :s AND m.created_at < :e"
        " ORDER BY m.created_at, m.id LIMIT :lim",
        v=variant_id,
        s=start,
        e=end,
        lim=STOCK_CARD_LIMIT,
    )
    return StockCardOut(
        variant=variant_brief(v),
        current_stock=v.stock,
        period_from=period.start_date,
        period_to=period.end_date,
        opening_balance=await balance_before(start),
        closing_balance=await balance_before(end),
        total_in=totals.qin,
        total_out=totals.qout,
        total_adjust=totals.qadj,
        total_reversal=totals.qrev,
        movements=[movement_out(r, p) for r in rows],
        truncated=totals.n > STOCK_CARD_LIMIT,
    )
