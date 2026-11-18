"""Periode laporan (batas hari WIB) & keamanan CSV."""

from datetime import UTC, date, datetime

import pytest

from bhv.services.csvexport import csv_line, safe_cell
from bhv.timeutil import PeriodError, fmt_wib, resolve_period, wib_midnight_utc


def test_wib_midnight_is_17_utc_previous_day() -> None:
    assert wib_midnight_utc(date(2026, 11, 17)) == datetime(2026, 11, 16, 17, 0, tzinfo=UTC)


def test_day_period_bounds() -> None:
    p = resolve_period("day", date(2026, 11, 17))
    assert (p.start_date, p.end_date) == (date(2026, 11, 17), date(2026, 11, 17))
    assert p.start_utc == datetime(2026, 11, 16, 17, tzinfo=UTC)
    assert p.end_utc == datetime(2026, 11, 17, 17, tzinfo=UTC)  # eksklusif
    assert p.label == "17/11/2026"


@pytest.mark.parametrize(
    ("on", "start", "end"),
    [
        (date(2026, 11, 17), date(2026, 11, 16), date(2026, 11, 22)),  # Selasa -> Senin..Minggu
        (date(2026, 11, 16), date(2026, 11, 16), date(2026, 11, 22)),  # Senin
        (date(2026, 11, 22), date(2026, 11, 16), date(2026, 11, 22)),  # Minggu
        (date(2026, 12, 31), date(2026, 12, 28), date(2027, 1, 3)),  # lintas tahun
    ],
)
def test_week_is_monday_to_sunday(on: date, start: date, end: date) -> None:
    p = resolve_period("week", on)
    assert (p.start_date, p.end_date) == (start, end)


@pytest.mark.parametrize(
    ("on", "end"),
    [
        (date(2026, 2, 10), date(2026, 2, 28)),
        (date(2028, 2, 10), date(2028, 2, 29)),  # kabisat
        (date(2026, 12, 31), date(2026, 12, 31)),
        (date(2026, 11, 1), date(2026, 11, 30)),
    ],
)
def test_month_is_calendar_month(on: date, end: date) -> None:
    p = resolve_period("month", on)
    assert p.start_date == on.replace(day=1) and p.end_date == end


def test_range_validation() -> None:
    p = resolve_period("range", date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))
    assert p.label == "01/01/2026 – 31/01/2026"
    with pytest.raises(PeriodError):
        resolve_period("range", date_from=date(2026, 2, 1), date_to=date(2026, 1, 1))
    with pytest.raises(PeriodError):
        resolve_period("range", date_from=date(2025, 1, 1), date_to=date(2026, 6, 1))
    with pytest.raises(PeriodError):
        resolve_period("range", date_from=date(2026, 1, 1))


def test_fmt_wib() -> None:
    assert fmt_wib(datetime(2026, 11, 16, 17, 30, tzinfo=UTC)) == "17/11/2026 00:30"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('=HYPERLINK("x")', '\'=HYPERLINK("x")'),
        ("+62", "'+62"),
        ("-Kemeja", "'-Kemeja"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("Kemeja", "Kemeja"),
        (-5, -5),  # angka negatif tetap angka
        (None, ""),
    ],
)
def test_csv_formula_injection_escaped(value: object, expected: object) -> None:
    assert safe_cell(value) == expected


def test_csv_line_semicolon_and_quoting() -> None:
    assert csv_line(["a;b", 'kata "x"', "baris\nbaru", 3]) == (
        '"a;b";"kata ""x""";"baris\nbaru";3\r\n'
    )
