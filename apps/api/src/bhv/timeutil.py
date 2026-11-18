"""Waktu: disimpan UTC, ditampilkan/dihitung per hari dalam WIB (Asia/Jakarta, UTC+7, tanpa DST)."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")


def now_utc() -> datetime:
    return datetime.now(UTC)


def today_wib() -> date:
    return datetime.now(WIB).date()
