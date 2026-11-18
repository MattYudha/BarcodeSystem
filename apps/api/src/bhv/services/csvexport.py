"""CSV untuk Excel Indonesia: UTF-8 + BOM, delimiter ';', aman dari CSV/formula injection."""

import csv
import io
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

from sqlalchemy import text

from bhv.db import get_sessionmaker

BOM = "﻿"
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    """Teks yang diawali karakter formula diberi prefiks ' agar tidak dieksekusi Excel.
    Angka dibiarkan (qty negatif tetap angka)."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return "" if value is None else value


def csv_line(values: Iterable[Any]) -> str:
    buf = io.StringIO()
    csv.writer(buf, delimiter=";", lineterminator="\r\n").writerow([safe_cell(v) for v in values])
    return buf.getvalue()


async def stream_csv(
    header: list[str], sql: str, params: dict[str, Any], to_row: Callable[[Any], list[Any]]
) -> AsyncIterator[str]:
    """Streaming baris dari DB (server-side cursor) tanpa memuat semua ke memori.
    Session dibuka sendiri karena generator berjalan setelah handler selesai."""
    yield BOM + csv_line(header)
    async with get_sessionmaker()() as session:
        result = await session.stream(text(sql), params)
        async for row in result:
            yield csv_line(to_row(row))
