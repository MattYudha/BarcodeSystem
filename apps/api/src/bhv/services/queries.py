"""Query transaksi bersama (daftar, kartu stok, dashboard, laporan) + aturan hak pembatalan."""

from datetime import datetime, timedelta
from typing import Any

from bhv.deps import Principal
from bhv.schemas_stock import MovementOut, UserBrief, VariantBrief
from bhv.timeutil import now_utc

STAFF_REVERSAL_WINDOW = timedelta(minutes=15)

MOVEMENT_SELECT = """
SELECT m.id, m.group_id::text AS group_id, m.type::text AS type, m.qty, m.balance_after,
       m.reason::text AS reason, m.production_date, m.batch_code, m.note,
       m.source::text AS source, m.created_at, m.reversal_of, m.opname_id,
       r.id AS reversed_by, o.type::text AS original_type,
       pv.id AS variant_id, pv.barcode, pv.size, pv.color,
       p.id AS product_id, p.code AS product_code, p.name AS product_name,
       c.name::text AS category_name,
       u.id AS user_id, u.name AS user_name, s.device_label
  FROM stock_movements m
  JOIN product_variants pv ON pv.id = m.variant_id
  JOIN products p ON p.id = pv.product_id
  JOIN categories c ON c.id = p.category_id
  JOIN users u ON u.id = m.user_id
  LEFT JOIN sessions s ON s.id = m.session_id
  LEFT JOIN stock_movements r ON r.reversal_of = m.id
  LEFT JOIN stock_movements o ON o.id = m.reversal_of
"""


def variant_brief(row: Any) -> VariantBrief:
    return VariantBrief(
        id=row.variant_id,
        barcode=row.barcode,
        size=row.size,
        color=row.color,
        product_id=row.product_id,
        product_code=row.product_code,
        product_name=row.product_name,
        category_name=row.category_name,
    )


def can_reverse(
    p: Principal | None, *, type_: str, user_id: int, created_at: datetime, reversed_by: Any
) -> bool:
    """Admin: semua transaksi yang belum dibatalkan. Staf: IN/OUT miliknya ≤ 15 menit."""
    if p is None or type_ == "REVERSAL" or reversed_by is not None:
        return False
    if p.is_admin:
        return True
    return (
        type_ in ("IN", "OUT")
        and user_id == p.user_id
        and now_utc() - created_at <= STAFF_REVERSAL_WINDOW
    )


def movement_out(row: Any, viewer: Principal | None = None) -> MovementOut:
    return MovementOut(
        id=row.id,
        group_id=row.group_id,
        type=row.type,
        qty=row.qty,
        balance_after=row.balance_after,
        reason=row.reason,
        production_date=row.production_date,
        batch_code=row.batch_code,
        note=row.note,
        source=row.source,
        created_at=row.created_at,
        reversal_of=row.reversal_of,
        reversed_by=row.reversed_by,
        original_type=row.original_type,
        opname_id=row.opname_id,
        variant=variant_brief(row),
        user=UserBrief(id=row.user_id, name=row.user_name),
        device_label=row.device_label,
        can_reverse=can_reverse(
            viewer,
            type_=row.type,
            user_id=row.user_id,
            created_at=row.created_at,
            reversed_by=row.reversed_by,
        ),
    )
