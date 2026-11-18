"""Waktu: disimpan UTC, ditampilkan/dihitung per hari dalam WIB (Asia/Jakarta, UTC+7, tanpa DST)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
PeriodKind = Literal["day", "week", "month", "range"]
MAX_RANGE_DAYS = 366


def now_utc() -> datetime:
    return datetime.now(UTC)


def today_wib() -> date:
    return datetime.now(WIB).date()


def wib_midnight_utc(d: date) -> datetime:
    """00:00 WIB pada tanggal d, dalam UTC."""
    return datetime.combine(d, time.min, tzinfo=WIB).astimezone(UTC)


def fmt_wib(dt: datetime) -> str:
    """DD/MM/YYYY HH:mm (WIB) untuk CSV/cetak."""
    return dt.astimezone(WIB).strftime("%d/%m/%Y %H:%M")


def fmt_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


@dataclass(frozen=True)
class Period:
    kind: PeriodKind
    start_date: date  # inklusif (WIB)
    end_date: date  # inklusif (WIB)

    @property
    def start_utc(self) -> datetime:
        return wib_midnight_utc(self.start_date)

    @property
    def end_utc(self) -> datetime:  # eksklusif
        return wib_midnight_utc(self.end_date + timedelta(days=1))

    @property
    def label(self) -> str:
        if self.start_date == self.end_date:
            return fmt_date(self.start_date)
        return f"{fmt_date(self.start_date)} – {fmt_date(self.end_date)}"


class PeriodError(ValueError):
    pass


def resolve_period(
    kind: PeriodKind,
    on: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Period:
    """Harian = 1 hari; mingguan = Senin–Minggu yang memuat `on`; bulanan = bulan kalender;
    range = date_from..date_to inklusif (maks 366 hari)."""
    if kind == "range":
        if date_from is None or date_to is None:
            raise PeriodError("Rentang tanggal wajib diisi (dari & sampai).")
        if date_to < date_from:
            raise PeriodError("Tanggal 'sampai' tidak boleh sebelum 'dari'.")
        if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
            raise PeriodError(f"Rentang maksimal {MAX_RANGE_DAYS} hari.")
        return Period("range", date_from, date_to)

    d = on or today_wib()
    if kind == "day":
        return Period("day", d, d)
    if kind == "week":
        start = d - timedelta(days=d.weekday())
        return Period("week", start, start + timedelta(days=6))
    start = d.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return Period("month", start, nxt - timedelta(days=1))
