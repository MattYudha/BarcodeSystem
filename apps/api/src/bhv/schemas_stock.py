"""Skema transaksi stok, opname, dashboard & laporan."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from bhv.schemas import BatchCode, Model, NoteText, ProductionDate, _empty_to_none

MovementType = Literal["IN", "OUT", "ADJUST", "REVERSAL"]
OutReason = Literal["sale", "return_to_production", "damaged", "other"]
ScanSource = Literal["scanner", "camera", "manual"]
Note = NoteText
RequiredNote = Annotated[str, BeforeValidator(_empty_to_none), Field(min_length=1, max_length=500)]
LineQty = Annotated[int, Field(ge=1, le=100_000)]

OUT_REASON_LABEL = {
    "sale": "Penjualan",
    "return_to_production": "Retur ke produksi",
    "damaged": "Rusak",
    "other": "Lainnya",
}
TYPE_LABEL = {"IN": "Masuk", "OUT": "Keluar", "ADJUST": "Penyesuaian", "REVERSAL": "Pembatalan"}


# ----------------------------------------------------------------------------- transaksi


class MovementLineIn(Model):
    variant_id: int
    qty: LineQty  # selalu positif; arah ditentukan tipe transaksi
    reason: OutReason | None = None
    production_date: ProductionDate = None
    batch_code: BatchCode = None
    note: Note = None


class MovementCreateIn(Model):
    """Satu submit keranjang scan (atau satu item pada mode per-item)."""

    type: Literal["IN", "OUT"]
    source: ScanSource = "scanner"
    lines: Annotated[list[MovementLineIn], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def _rules(self) -> "MovementCreateIn":
        for i, ln in enumerate(self.lines, 1):
            if self.type == "IN":
                if ln.reason is not None:
                    raise ValueError(f"Baris {i}: alasan hanya untuk barang keluar")
            else:
                if ln.reason is None:
                    raise ValueError(f"Baris {i}: alasan keluar wajib diisi")
                if ln.production_date or ln.batch_code:
                    raise ValueError(f"Baris {i}: tanggal produksi/batch hanya untuk barang masuk")
                if ln.reason == "other" and not ln.note:
                    raise ValueError(f"Baris {i}: alasan 'lainnya' wajib disertai catatan")
        return self


class AdjustLineIn(Model):
    variant_id: int
    qty: Annotated[int, Field(ge=-100_000, le=100_000)]  # bertanda; 0 ditolak
    note: RequiredNote

    @model_validator(mode="after")
    def _nonzero(self) -> "AdjustLineIn":
        if self.qty == 0:
            raise ValueError("Jumlah penyesuaian tidak boleh 0")
        return self


class AdjustIn(Model):
    lines: Annotated[list[AdjustLineIn], Field(min_length=1, max_length=200)]


class ReverseIn(Model):
    note: RequiredNote


class VariantBrief(BaseModel):
    id: int
    barcode: str
    size: str
    color: str | None
    product_id: int
    product_code: str
    product_name: str
    category_name: str


class UserBrief(BaseModel):
    id: int
    name: str


class MovementOut(BaseModel):
    id: int
    group_id: str | None
    type: MovementType
    qty: int  # bertanda
    balance_after: int
    reason: OutReason | None
    production_date: date | None
    batch_code: str | None
    note: str | None
    source: str
    created_at: datetime
    reversal_of: int | None
    reversed_by: int | None  # id transaksi pembatalan jika sudah dibatalkan
    original_type: MovementType | None  # untuk REVERSAL: tipe transaksi yang dibatalkan
    opname_id: int | None
    variant: VariantBrief
    user: UserBrief
    device_label: str | None
    can_reverse: bool = False


class MovementGroupOut(BaseModel):
    group_id: str
    type: MovementType
    replayed: bool  # True = Idempotency-Key sudah pernah diproses; tidak ada transaksi baru
    movements: list[MovementOut]


# ----------------------------------------------------------------------------- kartu stok


class StockCardOut(BaseModel):
    variant: VariantBrief
    current_stock: int
    period_from: date
    period_to: date
    opening_balance: int
    closing_balance: int
    total_in: int
    total_out: int
    total_adjust: int
    total_reversal: int
    movements: list[MovementOut]
    truncated: bool


# ----------------------------------------------------------------------------- opname

OpnameStatus = Literal["draft", "finalized", "cancelled"]


class OpnameCreateIn(Model):
    note: Note = None


class OpnameCountIn(Model):
    variant_id: int
    counted_qty: Annotated[int, Field(ge=0, le=1_000_000)]


class OpnameItemsIn(Model):
    items: Annotated[list[OpnameCountIn], Field(min_length=1, max_length=1000)]


class OpnameScanIn(Model):
    barcode: Annotated[str, Field(min_length=1, max_length=60)]
    increment: Annotated[int, Field(ge=1, le=10_000)] = 1


class OpnameItemOut(BaseModel):
    variant: VariantBrief
    counted_qty: int
    current_stock: int  # stok sistem saat ini (draft) / saat finalize (system_qty)
    diff: int  # counted_qty - current_stock
    counted_by: UserBrief
    counted_at: datetime


class OpnameOut(BaseModel):
    id: int
    code: str
    status: OpnameStatus
    note: str | None
    created_by: UserBrief
    created_at: datetime
    finalized_by: UserBrief | None
    finalized_at: datetime | None
    cancelled_at: datetime | None
    item_count: int
    diff_count: int
    items: list[OpnameItemOut]


# ----------------------------------------------------------------------------- dashboard


class DayPoint(BaseModel):
    date: date
    qty_in: int
    qty_out: int


class AlertItem(BaseModel):
    variant: VariantBrief
    stock: int
    min_stock: int


class DashboardOut(BaseModel):
    product_count: int
    variant_count: int
    total_stock: int
    in_today: int
    out_today: int
    alert_count: int
    alerts: list[AlertItem]
    last_7_days: list[DayPoint]
    recent: list[MovementOut]


# ----------------------------------------------------------------------------- laporan


class PeriodOut(BaseModel):
    kind: str
    start_date: date
    end_date: date
    label: str


class ReportRow(BaseModel):
    variant: VariantBrief
    opening: int
    qty_in: int
    qty_out: int  # positif
    qty_adjust: int  # bertanda
    qty_reversal: int  # bertanda
    closing: int
    tx_count: int


class ReportTotals(BaseModel):
    qty_in: int
    qty_out: int
    qty_adjust: int
    qty_reversal: int
    tx_count: int
    variant_count: int


class ReportSummaryOut(BaseModel):
    period: PeriodOut
    totals: ReportTotals
    rows: list[ReportRow]
