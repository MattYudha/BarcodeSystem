"""F-03/F-04 dashboard, F-15 laporan periode + CSV.

Definisi angka (konsisten di semua tempat):
- Laporan: per varian  saldo_akhir = saldo_awal + masuk - keluar + penyesuaian + pembatalan.
  Saldo awal = saldo transaksi terakhir sebelum awal periode. Batas hari = 00:00 WIB.
- Dashboard "masuk/keluar hari ini" & grafik 7 hari: transaksi IN/OUT yang TIDAK dibatalkan.
"""

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from bhv.db import fetch_all, fetch_one
from bhv.deps import DB, Admin, CurrentUser
from bhv.errors import AppError
from bhv.routers.movements import movement_filters
from bhv.schemas import Page
from bhv.schemas_stock import (
    OUT_REASON_LABEL,
    TYPE_LABEL,
    AlertItem,
    DashboardOut,
    DayPoint,
    MovementOut,
    MovementType,
    PeriodOut,
    ReportRow,
    ReportSummaryOut,
    ReportTotals,
)
from bhv.services.csvexport import stream_csv
from bhv.services.queries import MOVEMENT_SELECT, movement_out, variant_brief
from bhv.timeutil import (
    Period,
    PeriodError,
    PeriodKind,
    fmt_date,
    fmt_wib,
    resolve_period,
    today_wib,
    wib_midnight_utc,
)

router = APIRouter(tags=["reports"])

# ----------------------------------------------------------------------------- dashboard


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(p: CurrentUser, db: DB) -> DashboardOut:
    counts = await fetch_one(
        db,
        """SELECT (SELECT count(*) FROM products WHERE archived_at IS NULL) AS products,
                  count(*) FILTER (WHERE NOT is_archived) AS variants,
                  coalesce(sum(stock) FILTER (WHERE NOT is_archived), 0) AS stock,
                  count(*) FILTER (WHERE NOT is_archived AND is_alert) AS alerts
             FROM v_variant_stock""",
    )
    assert counts is not None
    today = today_wib()
    first = today - timedelta(days=6)
    daily = await fetch_all(
        db,
        """SELECT (m.created_at AT TIME ZONE 'Asia/Jakarta')::date AS d,
                  coalesce(sum(m.qty) FILTER (WHERE m.type = 'IN'), 0) AS qin,
                  coalesce(-sum(m.qty) FILTER (WHERE m.type = 'OUT'), 0) AS qout
             FROM stock_movements m
            WHERE m.created_at >= :start AND m.type IN ('IN', 'OUT')
              AND NOT EXISTS (SELECT 1 FROM stock_movements r WHERE r.reversal_of = m.id)
            GROUP BY 1""",
        start=wib_midnight_utc(first),
    )
    by_day = {r.d: r for r in daily}
    days = [
        DayPoint(
            date=d,
            qty_in=by_day[d].qin if d in by_day else 0,
            qty_out=by_day[d].qout if d in by_day else 0,
        )
        for d in (first + timedelta(days=i) for i in range(7))
    ]
    alerts = await fetch_all(
        db,
        """SELECT variant_id, barcode, size, color, product_id, product_code, product_name,
                  category_name, stock, min_stock
             FROM v_variant_stock
            WHERE NOT is_archived AND is_alert
            ORDER BY stock::numeric / min_stock, stock, product_name LIMIT 20""",
    )
    recent = await fetch_all(db, MOVEMENT_SELECT + " ORDER BY m.id DESC LIMIT 10")
    return DashboardOut(
        product_count=counts.products,
        variant_count=counts.variants,
        total_stock=counts.stock,
        in_today=days[-1].qty_in,
        out_today=days[-1].qty_out,
        alert_count=counts.alerts,
        alerts=[
            AlertItem(variant=variant_brief(a), stock=a.stock, min_stock=a.min_stock)
            for a in alerts
        ],  # fmt: skip
        last_7_days=days,
        recent=[movement_out(r, p) for r in recent],
    )


# ----------------------------------------------------------------------------- periode


def _period(
    kind: PeriodKind, on: date | None, date_from: date | None, date_to: date | None
) -> Period:
    try:
        return resolve_period(kind, on, date_from, date_to)
    except PeriodError as e:
        raise AppError("PERIOD_INVALID", message=str(e)) from None


def _period_out(p: Period) -> PeriodOut:
    return PeriodOut(kind=p.kind, start_date=p.start_date, end_date=p.end_date, label=p.label)


PeriodQ = Annotated[PeriodKind, Query(description="day | week | month | range")]
OnQ = Annotated[date | None, Query(alias="date", description="Tanggal acuan (default hari ini)")]


def _variant_filter(
    category_id: int | None, product_id: int | None, variant_id: int | None
) -> tuple[str, dict[str, Any]]:
    conds: list[str] = []
    params: dict[str, Any] = {}
    if category_id is not None:
        conds.append("p.category_id = :cat")
        params["cat"] = category_id
    if product_id is not None:
        conds.append("p.id = :pid")
        params["pid"] = product_id
    if variant_id is not None:
        conds.append("pv.id = :vid")
        params["vid"] = variant_id
    return "".join(" AND " + c for c in conds), params


_SUMMARY_SQL = """
WITH mv AS (
  SELECT m.variant_id,
         coalesce(sum(m.qty) FILTER (WHERE m.type = 'IN'), 0)        AS qty_in,
         coalesce(-sum(m.qty) FILTER (WHERE m.type = 'OUT'), 0)      AS qty_out,
         coalesce(sum(m.qty) FILTER (WHERE m.type = 'ADJUST'), 0)    AS qty_adjust,
         coalesce(sum(m.qty) FILTER (WHERE m.type = 'REVERSAL'), 0)  AS qty_reversal,
         count(*) AS tx_count
    FROM stock_movements m
    JOIN product_variants pv ON pv.id = m.variant_id
    JOIN products p ON p.id = pv.product_id
   WHERE m.created_at >= :start AND m.created_at < :end {vfilter}
   GROUP BY m.variant_id
), opening AS (
  SELECT DISTINCT ON (m.variant_id) m.variant_id, m.balance_after
    FROM stock_movements m
   WHERE m.created_at < :start AND m.variant_id IN (SELECT variant_id FROM mv)
   ORDER BY m.variant_id, m.created_at DESC, m.id DESC
)
SELECT vs.variant_id, vs.barcode, vs.size, vs.color, vs.product_id, vs.product_code,
       vs.product_name, vs.category_name,
       coalesce(o.balance_after, 0) AS opening, mv.qty_in, mv.qty_out, mv.qty_adjust,
       mv.qty_reversal, mv.tx_count,
       coalesce(o.balance_after, 0) + mv.qty_in - mv.qty_out + mv.qty_adjust + mv.qty_reversal
         AS closing
  FROM mv
  JOIN v_variant_stock vs ON vs.variant_id = mv.variant_id
  LEFT JOIN opening o ON o.variant_id = mv.variant_id
 ORDER BY vs.product_name, vs.product_id, vs.variant_id
"""


def _summary_query(
    period: Period, category_id: int | None, product_id: int | None, variant_id: int | None
) -> tuple[str, dict[str, Any]]:
    vf, params = _variant_filter(category_id, product_id, variant_id)
    return _SUMMARY_SQL.format(vfilter=vf), {
        **params, "start": period.start_utc, "end": period.end_utc,
    }  # fmt: skip


@router.get("/reports/summary", response_model=ReportSummaryOut)
async def report_summary(
    _: Admin,
    db: DB,
    period: PeriodQ = "day",
    on: OnQ = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
    product_id: int | None = None,
    variant_id: int | None = None,
) -> ReportSummaryOut:
    per = _period(period, on, date_from, date_to)
    sql, params = _summary_query(per, category_id, product_id, variant_id)
    rows = await fetch_all(db, sql, **params)
    out_rows = [
        ReportRow(
            variant=variant_brief(r),
            opening=r.opening,
            qty_in=r.qty_in,
            qty_out=r.qty_out,
            qty_adjust=r.qty_adjust,
            qty_reversal=r.qty_reversal,
            closing=r.closing,
            tx_count=r.tx_count,
        )  # fmt: skip
        for r in rows
    ]
    return ReportSummaryOut(
        period=_period_out(per),
        totals=ReportTotals(
            qty_in=sum(r.qty_in for r in out_rows),
            qty_out=sum(r.qty_out for r in out_rows),
            qty_adjust=sum(r.qty_adjust for r in out_rows),
            qty_reversal=sum(r.qty_reversal for r in out_rows),
            tx_count=sum(r.tx_count for r in out_rows),
            variant_count=len(out_rows),
        ),
        rows=out_rows,
    )


@router.get("/reports/summary.csv", response_class=StreamingResponse)
async def report_summary_csv(
    _: Admin,
    period: PeriodQ = "day",
    on: OnQ = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
    product_id: int | None = None,
    variant_id: int | None = None,
) -> StreamingResponse:
    per = _period(period, on, date_from, date_to)
    sql, params = _summary_query(per, category_id, product_id, variant_id)
    header = ["Barcode", "Kode Barang", "Nama Barang", "Kategori", "Ukuran", "Warna",
              "Saldo Awal", "Masuk", "Keluar", "Penyesuaian", "Pembatalan", "Saldo Akhir",
              "Jumlah Transaksi"]  # fmt: skip

    def row(r: Any) -> list[Any]:
        return [r.barcode, r.product_code, r.product_name, r.category_name, r.size, r.color,
                r.opening, r.qty_in, r.qty_out, r.qty_adjust, r.qty_reversal, r.closing,
                r.tx_count]  # fmt: skip

    return _csv_response(f"ringkasan-stok-{_fname(per)}.csv", header, sql, params, row)


# ----------------------------------------------------------------------------- transaksi


def _report_movement_filters(
    per: Period, types: list[MovementType] | None, category_id: int | None,
    product_id: int | None, variant_id: int | None, user_id: int | None, q: str | None,
) -> tuple[str, dict[str, Any]]:  # fmt: skip
    return movement_filters(
        date_from=per.start_date, date_to=per.end_date, types=types, variant_id=variant_id,
        product_id=product_id, category_id=category_id, user_id=user_id, q=q,
    )  # fmt: skip


@router.get("/reports/movements", response_model=Page[MovementOut])
async def report_movements(
    p: Admin,
    db: DB,
    period: PeriodQ = "day",
    on: OnQ = None,
    date_from: date | None = None,
    date_to: date | None = None,
    type: Annotated[list[MovementType] | None, Query()] = None,  # noqa: A002
    category_id: int | None = None,
    product_id: int | None = None,
    variant_id: int | None = None,
    user_id: int | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[MovementOut]:
    per = _period(period, on, date_from, date_to)
    where, params = _report_movement_filters(
        per, type, category_id, product_id, variant_id, user_id, q
    )
    total = await fetch_one(
        db,
        "SELECT count(*) AS n FROM stock_movements m"
        " JOIN product_variants pv ON pv.id = m.variant_id"
        " JOIN products p ON p.id = pv.product_id" + where,
        **params,
    )
    rows = await fetch_all(
        db,
        MOVEMENT_SELECT + where + " ORDER BY m.created_at, m.id LIMIT :limit OFFSET :offset",
        **params,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return Page[MovementOut](
        items=[movement_out(r, p) for r in rows],
        total=total.n if total else 0,
        page=page,
        page_size=page_size,
    )


@router.get("/reports/movements.csv", response_class=StreamingResponse)
async def report_movements_csv(
    _: Admin,
    period: PeriodQ = "day",
    on: OnQ = None,
    date_from: date | None = None,
    date_to: date | None = None,
    type: Annotated[list[MovementType] | None, Query()] = None,  # noqa: A002
    category_id: int | None = None,
    product_id: int | None = None,
    variant_id: int | None = None,
    user_id: int | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> StreamingResponse:
    per = _period(period, on, date_from, date_to)
    where, params = _report_movement_filters(
        per, type, category_id, product_id, variant_id, user_id, q
    )
    header = ["Waktu (WIB)", "No Transaksi", "Tipe", "Barcode", "Kode Barang", "Nama Barang",
              "Kategori", "Ukuran", "Warna", "Qty", "Saldo Setelah", "Alasan Keluar",
              "Tgl Produksi", "Batch", "Catatan", "Petugas", "Perangkat", "Keterangan"]  # fmt: skip

    def row(r: Any) -> list[Any]:
        info = ""
        if r.reversal_of:
            info = f"Membatalkan #{r.reversal_of} ({TYPE_LABEL.get(r.original_type or '', '')})"
        elif r.reversed_by:
            info = f"Dibatalkan oleh #{r.reversed_by}"
        return [
            fmt_wib(r.created_at), r.id, TYPE_LABEL[r.type], r.barcode, r.product_code,
            r.product_name, r.category_name, r.size, r.color, r.qty, r.balance_after,
            OUT_REASON_LABEL.get(r.reason or "", ""),
            fmt_date(r.production_date) if r.production_date else "", r.batch_code, r.note,
            r.user_name, r.device_label, info,
        ]  # fmt: skip

    sql = MOVEMENT_SELECT + where + " ORDER BY m.created_at, m.id"
    return _csv_response(f"transaksi-{_fname(per)}.csv", header, sql, params, row)


@router.get("/reports/stock.csv", response_class=StreamingResponse)
async def report_stock_csv(
    _: Admin, category_id: int | None = None, include_archived: bool = False
) -> StreamingResponse:
    """Posisi stok saat ini per varian."""
    conds, params = [], {}
    if not include_archived:
        conds.append("NOT is_archived")
    if category_id is not None:
        conds.append("category_id = :cat")
        params["cat"] = category_id
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    sql = (
        "SELECT barcode, product_code, product_name, category_name, size, color, price, stock,"
        f" min_stock, stock_status, is_archived FROM v_variant_stock{where}"
        " ORDER BY product_name, product_id, variant_id"
    )
    status = {"ok": "Aman", "low": "Menipis", "out": "Habis"}
    header = ["Barcode", "Kode Barang", "Nama Barang", "Kategori", "Ukuran", "Warna", "Harga",
              "Stok", "Stok Minimum", "Status", "Diarsipkan"]  # fmt: skip

    def row(r: Any) -> list[Any]:
        price = "" if r.price is None else f"{r.price:.2f}".replace(".", ",")
        return [r.barcode, r.product_code, r.product_name, r.category_name, r.size, r.color,
                price, r.stock, r.min_stock, status[r.stock_status],
                "Ya" if r.is_archived else "Tidak"]  # fmt: skip

    return _csv_response(f"stok-{today_wib():%Y-%m-%d}.csv", header, sql, params, row)


def _fname(per: Period) -> str:
    if per.start_date == per.end_date:
        return f"{per.start_date:%Y-%m-%d}"
    return f"{per.start_date:%Y-%m-%d}_{per.end_date:%Y-%m-%d}"


def _csv_response(
    filename: str, header: list[str], sql: str, params: dict[str, Any], to_row: Any
) -> StreamingResponse:
    return StreamingResponse(
        stream_csv(header, sql, params, to_row),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
