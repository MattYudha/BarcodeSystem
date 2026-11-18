"""Barang (model), varian (ukuran/warna + barcode), barcode SVG dan cetak label PDF."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from bhv.audit import audit
from bhv.db import execute, fetch_all, fetch_one, fetch_val
from bhv.deps import DB, Admin, CurrentUser, Principal
from bhv.errors import AppError
from bhv.schemas import (
    ArchivedFilter,
    CategoryRef,
    LabelRequestIn,
    Page,
    ProductCreateIn,
    ProductOut,
    ProductPatchIn,
    VariantIn,
    VariantOut,
    VariantPatchIn,
)
from bhv.services.labels import (
    MAX_LABELS_PER_JOB,
    LabelData,
    LabelTooSmall,
    barcode_svg,
    render_labels_pdf,
)
from bhv.services.movements import Line, insert_group
from bhv.timeutil import now_utc

router = APIRouter(tags=["catalog"])

StatusFilter = Annotated[str | None, Query(pattern="^(ok|low|out|alert)$")]
PageNo = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]

# Kondisi status stok untuk alias varian `pv` (konsisten dengan view v_variant_stock).
_STATUS_SQL = {
    "out": "{a}.stock = 0",
    "low": "{a}.stock > 0 AND {a}.stock <= {a}.min_stock",
    "ok": "{a}.stock > {a}.min_stock",
    "alert": "{a}.min_stock > 0 AND {a}.stock <= {a}.min_stock",
}


def like(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_VARIANT_SELECT = """
SELECT vs.variant_id AS id, vs.product_id, vs.product_code, vs.product_name, vs.category_id,
       vs.category_name, vs.price, vs.barcode, vs.size, vs.color, vs.min_stock, vs.stock,
       vs.stock_status, vs.is_alert, vs.is_archived,
       EXISTS (SELECT 1 FROM stock_movements m WHERE m.variant_id = vs.variant_id) AS has_movements
  FROM v_variant_stock vs
"""


def _variant(row: Any) -> VariantOut:
    return VariantOut.model_validate(row._mapping)


async def _get_variant(db: AsyncSession, variant_id: int) -> VariantOut:
    row = await fetch_one(db, _VARIANT_SELECT + " WHERE vs.variant_id = :id", id=variant_id)
    if row is None:
        raise AppError("VARIANT_NOT_FOUND")
    return _variant(row)


_PRODUCT_SELECT = """
SELECT p.id, p.code, p.name, p.description, p.price, p.archived_at, p.created_at, p.updated_at,
       c.id AS category_id, c.name::text AS category_name,
       (SELECT count(*) FROM product_variants pv
         WHERE pv.product_id = p.id AND pv.archived_at IS NULL) AS variant_count,
       (SELECT coalesce(sum(pv.stock), 0) FROM product_variants pv
         WHERE pv.product_id = p.id) AS total_stock,
       (SELECT count(*) FROM product_variants pv
         WHERE pv.product_id = p.id AND pv.archived_at IS NULL
           AND pv.min_stock > 0 AND pv.stock <= pv.min_stock) AS alert_count,
       EXISTS (SELECT 1 FROM stock_movements m JOIN product_variants pv ON pv.id = m.variant_id
                WHERE pv.product_id = p.id) AS has_movements
  FROM products p JOIN categories c ON c.id = p.category_id
"""


async def _products_out(db: AsyncSession, rows: list[Any]) -> list[ProductOut]:
    if not rows:
        return []
    ids = [r.id for r in rows]
    variants = await fetch_all(
        db, _VARIANT_SELECT + " WHERE vs.product_id = ANY(:ids) ORDER BY vs.variant_id", ids=ids
    )
    by_product: dict[int, list[VariantOut]] = {}
    for v in variants:
        by_product.setdefault(v.product_id, []).append(_variant(v))
    return [
        ProductOut(
            **{
                k: getattr(r, k)
                for k in (
                    "id",
                    "code",
                    "name",
                    "description",
                    "price",
                    "archived_at",
                    "created_at",
                    "updated_at",
                    "variant_count",
                    "total_stock",
                    "alert_count",
                    "has_movements",
                )
            },
            category=CategoryRef(id=r.category_id, name=r.category_name),
            variants=by_product.get(r.id, []),
        )  # fmt: skip
        for r in rows
    ]


async def _get_product(db: AsyncSession, product_id: int) -> ProductOut:
    row = await fetch_one(db, _PRODUCT_SELECT + " WHERE p.id = :id", id=product_id)
    if row is None:
        raise AppError("PRODUCT_NOT_FOUND")
    return (await _products_out(db, [row]))[0]


async def _require_active_category(db: AsyncSession, category_id: int) -> None:
    archived = await fetch_one(
        db, "SELECT archived_at FROM categories WHERE id = :id FOR SHARE", id=category_id
    )
    if archived is None:
        raise AppError("CATEGORY_NOT_FOUND")
    if archived.archived_at is not None:
        raise AppError("CATEGORY_ARCHIVED")


async def _create_variants(
    db: AsyncSession, actor: Principal, product_id: int, variants: list[VariantIn]
) -> list[int]:
    """Insert varian (barcode dari trigger) + transaksi IN 'Stok awal' dalam satu transaksi."""
    ids: list[int] = []
    initial: list[Line] = []
    for v in variants:
        vid = await fetch_val(
            db,
            """INSERT INTO product_variants (product_id, size, color, min_stock)
               VALUES (:pid, :size, :color, :min) RETURNING id""",
            pid=product_id,
            size=v.size,
            color=v.color,
            min=v.min_stock,
        )
        ids.append(int(vid))
        if v.initial_stock > 0:
            initial.append(
                Line(
                    variant_id=int(vid),
                    qty=v.initial_stock,
                    production_date=v.production_date,
                    batch_code=v.batch_code,
                    note="Stok awal",
                    source="initial",
                )
            )
    if initial:
        await insert_group(db, actor, "IN", initial)
    return ids


# ------------------------------------------------------------------------------- products


@router.get("/products", response_model=Page[ProductOut])
async def list_products(
    _: CurrentUser,
    db: DB,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category_id: int | None = None,
    size: Annotated[str | None, Query(max_length=20)] = None,
    stock_status: StatusFilter = None,
    archived: ArchivedFilter = "active",
    page: PageNo = 1,
    page_size: PageSize = 50,
) -> Page[ProductOut]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if q and q.strip():
        where.append(
            "(p.name ILIKE :q OR p.code ILIKE :q OR EXISTS (SELECT 1 FROM product_variants pv"
            " WHERE pv.product_id = p.id AND pv.barcode ILIKE :q))"
        )
        params["q"] = like(q.strip())
    if category_id is not None:
        where.append("p.category_id = :cat")
        params["cat"] = category_id
    if archived == "active":
        where.append("p.archived_at IS NULL")
    elif archived == "archived":
        where.append("p.archived_at IS NOT NULL")
    variant_conds = ["pv.archived_at IS NULL"]
    if size and size.strip():
        variant_conds.append("pv.size = :size")
        params["size"] = size.strip().upper()
    if stock_status:
        variant_conds.append(_STATUS_SQL[stock_status].format(a="pv"))
    if len(variant_conds) > 1:
        where.append(
            "EXISTS (SELECT 1 FROM product_variants pv WHERE pv.product_id = p.id AND "
            + " AND ".join(variant_conds)
            + ")"
        )
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    total = await fetch_val(
        db, "SELECT count(*) FROM products p JOIN categories c ON c.id = p.category_id" + where_sql,
        **params,
    )  # fmt: skip
    rows = await fetch_all(
        db,
        _PRODUCT_SELECT + where_sql + " ORDER BY p.name, p.id LIMIT :limit OFFSET :offset",
        **params,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return Page[ProductOut](
        items=await _products_out(db, rows), total=total, page=page, page_size=page_size
    )


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(body: ProductCreateIn, admin: Admin, db: DB) -> ProductOut:
    await _require_active_category(db, body.category_id)
    pid = await fetch_val(
        db,
        """INSERT INTO products (category_id, name, description, price, created_by)
           VALUES (:cat, :name, :desc, :price, :by) RETURNING id""",
        cat=body.category_id,
        name=body.name,
        desc=body.description,
        price=body.price,
        by=admin.user_id,
    )
    await _create_variants(db, admin, int(pid), body.variants)
    out = await _get_product(db, int(pid))
    await audit(db, admin, "product.create", "product", out.id, after=body.model_dump(mode="json"))
    await db.commit()
    return out


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, _: CurrentUser, db: DB) -> ProductOut:
    return await _get_product(db, product_id)


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(product_id: int, body: ProductPatchIn, admin: Admin, db: DB) -> ProductOut:
    before = await _get_product(db, product_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        changes.pop("name")
    if "category_id" in changes:
        if changes["category_id"] is None:
            changes.pop("category_id")
        elif changes["category_id"] != before.category.id:
            await _require_active_category(db, changes["category_id"])
    if changes:
        cols = {"category_id": "category_id", "name": "name", "description": "description",
                "price": "price"}  # fmt: skip
        sets = ", ".join(f"{cols[k]} = :{k}" for k in changes)
        await execute(db, f"UPDATE products SET {sets} WHERE id = :id", id=product_id, **changes)
        await audit(
            db, admin, "product.update", "product", product_id,
            before={k: (before.category.id if k == "category_id" else getattr(before, k))
                    for k in changes},
            after=body.model_dump(mode="json", exclude_unset=True),
        )  # fmt: skip
    out = await _get_product(db, product_id)
    await db.commit()
    return out


async def _archive_product(db: AsyncSession, admin: Principal, pid: int, on: bool) -> ProductOut:
    await _get_product(db, pid)
    expr = "coalesce(archived_at, now())" if on else "NULL"
    await execute(db, f"UPDATE products SET archived_at = {expr} WHERE id = :id", id=pid)
    await audit(db, admin, "product.archive" if on else "product.unarchive", "product", pid)
    out = await _get_product(db, pid)
    await db.commit()
    return out


@router.post("/products/{product_id}/archive", response_model=ProductOut)
async def archive_product(product_id: int, admin: Admin, db: DB) -> ProductOut:
    return await _archive_product(db, admin, product_id, True)


@router.post("/products/{product_id}/unarchive", response_model=ProductOut)
async def unarchive_product(product_id: int, admin: Admin, db: DB) -> ProductOut:
    return await _archive_product(db, admin, product_id, False)


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(product_id: int, admin: Admin, db: DB) -> None:
    """Hapus permanen hanya untuk barang salah input yang belum punya transaksi sama sekali."""
    locked = await fetch_one(db, "SELECT id FROM products WHERE id = :id FOR UPDATE", id=product_id)
    if locked is None:
        raise AppError("PRODUCT_NOT_FOUND")
    before = await _get_product(db, product_id)
    if before.has_movements:
        raise AppError("PRODUCT_HAS_MOVEMENTS")
    await execute(db, "DELETE FROM product_variants WHERE product_id = :id", id=product_id)
    await execute(db, "DELETE FROM products WHERE id = :id", id=product_id)
    await audit(db, admin, "product.delete", "product", product_id,
                before=before.model_dump(mode="json"))  # fmt: skip
    await db.commit()


@router.post("/products/{product_id}/variants", response_model=VariantOut, status_code=201)
async def add_variant(product_id: int, body: VariantIn, admin: Admin, db: DB) -> VariantOut:
    await _get_product(db, product_id)
    [vid] = await _create_variants(db, admin, product_id, [body])
    out = await _get_variant(db, vid)
    await audit(db, admin, "variant.create", "variant", vid, after=body.model_dump(mode="json"))
    await db.commit()
    return out


# ------------------------------------------------------------------------------- variants


@router.get("/variants", response_model=Page[VariantOut])
async def list_variants(
    _: CurrentUser,
    db: DB,
    q: Annotated[str | None, Query(max_length=100)] = None,
    product_id: int | None = None,
    category_id: int | None = None,
    size: Annotated[str | None, Query(max_length=20)] = None,
    stock_status: StatusFilter = None,
    archived: ArchivedFilter = "active",
    page: PageNo = 1,
    page_size: PageSize = 50,
) -> Page[VariantOut]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if q and q.strip():
        where.append(
            "(vs.product_name ILIKE :q OR vs.product_code ILIKE :q OR vs.barcode ILIKE :q)"
        )
        params["q"] = like(q.strip())
    if product_id is not None:
        where.append("vs.product_id = :pid")
        params["pid"] = product_id
    if category_id is not None:
        where.append("vs.category_id = :cat")
        params["cat"] = category_id
    if size and size.strip():
        where.append("vs.size = :size")
        params["size"] = size.strip().upper()
    if stock_status:
        where.append(_STATUS_SQL[stock_status].format(a="vs"))
    if archived == "active":
        where.append("NOT vs.is_archived")
    elif archived == "archived":
        where.append("vs.is_archived")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = await fetch_val(db, "SELECT count(*) FROM v_variant_stock vs" + where_sql, **params)
    rows = await fetch_all(
        db,
        _VARIANT_SELECT + where_sql
        + " ORDER BY vs.product_name, vs.product_id, vs.variant_id LIMIT :limit OFFSET :offset",
        **params,
        limit=page_size,
        offset=(page - 1) * page_size,
    )  # fmt: skip
    return Page[VariantOut](
        items=[_variant(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/variants/lookup", response_model=VariantOut)
async def lookup_variant(
    _: CurrentUser, db: DB, barcode: Annotated[str, Query(min_length=1, max_length=60)]
) -> VariantOut:
    """Dipakai halaman scan. Barcode tak dikenal -> 404, barang arsip -> 409 (tanpa transaksi)."""
    code = barcode.strip().upper()
    row = await fetch_one(db, _VARIANT_SELECT + " WHERE vs.barcode = :b", b=code)
    if row is None:
        raise AppError("VARIANT_NOT_FOUND", {"barcode": code})
    v = _variant(row)
    if v.is_archived:
        raise AppError("VARIANT_ARCHIVED", {"barcode": code, "variant_id": v.id})
    return v


@router.get("/variants/{variant_id}", response_model=VariantOut)
async def get_variant(variant_id: int, _: CurrentUser, db: DB) -> VariantOut:
    return await _get_variant(db, variant_id)


@router.patch("/variants/{variant_id}", response_model=VariantOut)
async def update_variant(variant_id: int, body: VariantPatchIn, admin: Admin, db: DB) -> VariantOut:
    locked = await fetch_one(
        db, "SELECT id FROM product_variants WHERE id = :id FOR UPDATE", id=variant_id
    )
    if locked is None:
        raise AppError("VARIANT_NOT_FOUND")
    before = await _get_variant(db, variant_id)
    changes = body.model_dump(exclude_unset=True)
    for k in ("size", "min_stock"):
        if k in changes and changes[k] is None:
            changes.pop(k)
    identity_change = ("size" in changes and changes["size"] != before.size) or (
        "color" in changes and (changes["color"] or "").lower() != (before.color or "").lower()
    )
    if identity_change and before.has_movements:
        raise AppError("VARIANT_HAS_MOVEMENTS")
    if changes:
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        await execute(db, f"UPDATE product_variants SET {sets} WHERE id = :id", id=variant_id,
                      **changes)  # fmt: skip
        await audit(db, admin, "variant.update", "variant", variant_id,
                    before={k: getattr(before, k) for k in changes}, after=changes)  # fmt: skip
    out = await _get_variant(db, variant_id)
    await db.commit()
    return out


async def _archive_variant(db: AsyncSession, admin: Principal, vid: int, on: bool) -> VariantOut:
    row = await fetch_one(
        db,
        """SELECT pv.id, p.archived_at AS product_archived FROM product_variants pv
             JOIN products p ON p.id = pv.product_id WHERE pv.id = :id FOR UPDATE OF pv""",
        id=vid,
    )
    if row is None:
        raise AppError("VARIANT_NOT_FOUND")
    if not on and row.product_archived is not None:
        raise AppError("PRODUCT_ARCHIVED", message="Pulihkan barangnya dulu sebelum varian.")
    expr = "coalesce(archived_at, now())" if on else "NULL"
    await execute(db, f"UPDATE product_variants SET archived_at = {expr} WHERE id = :id", id=vid)
    await audit(db, admin, "variant.archive" if on else "variant.unarchive", "variant", vid)
    out = await _get_variant(db, vid)
    await db.commit()
    return out


@router.post("/variants/{variant_id}/archive", response_model=VariantOut)
async def archive_variant(variant_id: int, admin: Admin, db: DB) -> VariantOut:
    return await _archive_variant(db, admin, variant_id, True)


@router.post("/variants/{variant_id}/unarchive", response_model=VariantOut)
async def unarchive_variant(variant_id: int, admin: Admin, db: DB) -> VariantOut:
    return await _archive_variant(db, admin, variant_id, False)


@router.get(
    "/variants/{variant_id}/barcode.svg",
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}}},
)
async def variant_barcode_svg(variant_id: int, _: CurrentUser, db: DB) -> Response:
    code = await fetch_val(db, "SELECT barcode FROM product_variants WHERE id = :id", id=variant_id)
    if code is None:
        raise AppError("VARIANT_NOT_FOUND")
    return Response(
        barcode_svg(code),
        media_type="image/svg+xml",
        # Barcode tidak pernah berubah -> aman di-cache lama (private: butuh login).
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


# ------------------------------------------------------------------------------- label


@router.post(
    "/labels/pdf", response_class=Response, responses={200: {"content": {"application/pdf": {}}}}
)
async def print_labels(body: LabelRequestIn, user: CurrentUser, db: DB) -> Response:
    """Admin & staf boleh cetak (ulang) label."""
    total = sum(i.copies for i in body.items)
    if total > MAX_LABELS_PER_JOB:
        raise AppError("LABEL_LIMIT", {"max": MAX_LABELS_PER_JOB, "requested": total})
    ids = list({i.variant_id for i in body.items})
    rows = await fetch_all(
        db,
        """SELECT variant_id, barcode, product_name, size, color, price
             FROM v_variant_stock WHERE variant_id = ANY(:ids)""",
        ids=ids,
    )
    found = {r.variant_id: r for r in rows}
    missing = sorted(set(ids) - found.keys())
    if missing:
        raise AppError("VARIANT_NOT_FOUND", {"variant_ids": missing})

    labels = [
        LabelData(r.barcode, r.product_name, r.size, r.color, r.price)
        for item in body.items
        for r in [found[item.variant_id]]
        for _ in range(item.copies)
    ]
    try:
        pdf = render_labels_pdf(
            body.template, labels, show_price=body.show_price, start_position=body.start_position
        )
    except LabelTooSmall as e:
        raise AppError("LABEL_TOO_SMALL", {"barcode": e.barcode, "template": e.template}) from e
    await audit(db, user, "label.print", None, None,
                after={"template": body.template, "total": total,
                       "items": [i.model_dump() for i in body.items]})  # fmt: skip
    await db.commit()
    stamp = datetime.strftime(now_utc(), "%Y%m%d-%H%M%S")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="label-{stamp}.pdf"'},
    )
