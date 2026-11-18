"""F-03/F-04 dashboard, F-15 laporan periode + CSV (batas hari WIB)."""

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from e2e_support import Api, create_product, post_movement

from bhv.timeutil import today_wib


@pytest.fixture
def product(admin: Api, category: dict[str, Any]) -> dict[str, Any]:
    return create_product(admin, category["id"], variants=[
        {"size": "M", "min_stock": 5}, {"size": "L", "min_stock": 0},
    ])  # fmt: skip


def _v(product: dict[str, Any], size: str) -> dict[str, Any]:
    return next(v for v in product["variants"] if v["size"] == size)


def backfill(
    pg: psycopg.Connection, variant_id: int, user_id: int,
    entries: list[tuple[datetime, str, int, str | None]],
) -> None:  # fmt: skip
    """Tulis riwayat dengan waktu lampau (hanya untuk test; trigger memaksa waktu server).
    Saldo dihitung di sini persis seperti trigger. Varian harus belum punya transaksi."""
    balance = 0
    with pg.transaction():
        pg.execute("SET LOCAL session_replication_role = replica")
        for ts, type_, qty, reason in sorted(entries):
            balance += qty
            assert balance >= 0
            pg.execute(
                "INSERT INTO stock_movements (variant_id, type, qty, balance_after, reason, source,"
                " user_id, created_at, note) VALUES (%s,%s,%s,%s,%s,'manual',%s,%s,%s)",
                (variant_id, type_, qty, balance, reason, user_id, ts,
                 "x" if type_ == "ADJUST" else None),
            )  # fmt: skip
        pg.execute("UPDATE product_variants SET stock = %s WHERE id = %s", (balance, variant_id))


def wib(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC) - timedelta(hours=7)


def test_daily_report_respects_wib_boundaries(
    admin: Api, product: dict[str, Any], pg: psycopg.Connection
) -> None:
    vid = _v(product, "M")["id"]
    backfill(pg, vid, admin.me["id"], [  # type: ignore[index]
        (wib(2026, 3, 9, 23, 59), "IN", 10, None),    # 9 Maret WIB (16:59 UTC)
        (wib(2026, 3, 10, 0, 0), "IN", 5, None),      # 10 Maret 00:00 WIB = 9 Maret 17:00 UTC
        (wib(2026, 3, 10, 12, 0), "OUT", -3, "sale"),
        (wib(2026, 3, 10, 23, 59), "ADJUST", -1, None),
        (wib(2026, 3, 11, 0, 0), "OUT", -2, "damaged"),
    ])  # fmt: skip
    rep = admin.ok(
        "GET", "/reports/summary", params={"period": "day", "date": "2026-03-10", "variant_id": vid}
    )
    assert rep["period"]["label"] == "10/03/2026"
    [row] = rep["rows"]
    assert (row["opening"], row["qty_in"], row["qty_out"], row["qty_adjust"], row["closing"], row["tx_count"]) == (
        10, 5, 3, -1, 11, 3,
    )  # fmt: skip
    # Identitas: saldo akhir hari ini = saldo awal hari berikutnya
    nxt = admin.ok(
        "GET", "/reports/summary", params={"period": "day", "date": "2026-03-11", "variant_id": vid}
    )
    assert nxt["rows"][0]["opening"] == 11 and nxt["rows"][0]["closing"] == 9

    week = admin.ok(
        "GET",
        "/reports/summary",
        params={"period": "week", "date": "2026-03-11", "variant_id": vid},
    )
    assert (week["period"]["start_date"], week["period"]["end_date"]) == (
        "2026-03-09",
        "2026-03-15",
    )
    assert (week["rows"][0]["opening"], week["rows"][0]["closing"], week["totals"]["tx_count"]) == (
        0,
        9,
        5,
    )
    month = admin.ok(
        "GET",
        "/reports/summary",
        params={"period": "month", "date": "2026-03-01", "variant_id": vid},
    )
    assert month["rows"][0]["closing"] == 9

    lst = admin.ok(
        "GET",
        "/reports/movements",
        params={"period": "day", "date": "2026-03-10", "variant_id": vid},
    )
    assert [m["qty"] for m in lst["items"]] == [5, -3, -1]


def test_report_identity_with_reversal(admin: Api, product: dict[str, Any]) -> None:
    vid = _v(product, "M")["id"]
    post_movement(admin, "IN", [{"variant_id": vid, "qty": 10}])
    out = post_movement(admin, "OUT", [{"variant_id": vid, "qty": 4, "reason": "sale"}]).json()
    admin.ok("POST", f"/movements/{out['movements'][0]['id']}/reverse", json={"note": "batal"})
    rep = admin.ok("GET", "/reports/summary", params={"period": "day", "product_id": product["id"]})
    [row] = [r for r in rep["rows"] if r["variant"]["id"] == vid]
    assert (row["qty_in"], row["qty_out"], row["qty_reversal"], row["closing"]) == (10, 4, 4, 10)
    assert (
        row["opening"] + row["qty_in"] - row["qty_out"] + row["qty_adjust"] + row["qty_reversal"]
        == row["closing"]
    )
    assert rep["totals"]["variant_count"] == 1  # varian L tanpa transaksi tidak muncul


def test_dashboard_counts_effective_today(admin: Api, staff: Api, product: dict[str, Any]) -> None:
    m, l_ = _v(product, "M"), _v(product, "L")
    before = staff.ok("GET", "/dashboard")
    post_movement(
        staff, "IN", [{"variant_id": m["id"], "qty": 7}, {"variant_id": l_["id"], "qty": 2}]
    )
    wrong = post_movement(staff, "IN", [{"variant_id": l_["id"], "qty": 100}]).json()
    staff.ok(
        "POST", f"/movements/{wrong['movements'][0]['id']}/reverse", json={"note": "salah qty"}
    )
    post_movement(staff, "OUT", [{"variant_id": m["id"], "qty": 3, "reason": "sale"}])
    after = staff.ok("GET", "/dashboard")
    assert after["in_today"] - before["in_today"] == 9  # 100 yang dibatalkan tidak dihitung
    assert after["out_today"] - before["out_today"] == 3
    assert after["total_stock"] - before["total_stock"] == 6
    assert after["last_7_days"][-1] == {"date": today_wib().isoformat(), "qty_in": after["in_today"],
                                        "qty_out": after["out_today"]}  # fmt: skip
    assert len(after["last_7_days"]) == 7
    # M stok 4 <= min 5 -> peringatan menipis
    alerts = staff.ok(
        "GET", "/variants", params={"product_id": product["id"], "stock_status": "alert"}
    )
    assert [a["id"] for a in alerts["items"]] == [m["id"]]
    assert after["alert_count"] >= 1 and len(after["alerts"]) <= 20
    ratios = [a["stock"] / a["min_stock"] for a in after["alerts"]]
    assert ratios == sorted(ratios)  # paling kritis lebih dulu
    assert after["recent"][0]["type"] == "OUT"


def _read_csv(r: Any) -> list[list[str]]:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    raw = r.content.decode("utf-8")
    assert raw.startswith("﻿")
    return list(csv.reader(io.StringIO(raw[1:]), delimiter=";"))


def test_csv_exports(admin: Api, category: dict[str, Any], pg: psycopg.Connection) -> None:
    p = create_product(admin, category["id"], name=f"=HYPERLINK(evil) {uuid.uuid4().hex[:4]}",
                       variants=[{"size": "M", "color": "Merah"}])  # fmt: skip
    vid = p["variants"][0]["id"]
    backfill(pg, vid, admin.me["id"], [(wib(2026, 4, 1, 0, 30), "IN", 12, None),  # type: ignore[index]
                                       (wib(2026, 4, 1, 15, 45), "OUT", -2, "return_to_production")])  # fmt: skip
    rows = _read_csv(admin.get("/reports/movements.csv",
                               params={"period": "day", "date": "2026-04-01", "variant_id": vid}))  # fmt: skip
    assert rows[0][:3] == ["Waktu (WIB)", "No Transaksi", "Tipe"]
    assert [r[0] for r in rows[1:]] == ["01/04/2026 00:30", "01/04/2026 15:45"]
    assert [r[2] for r in rows[1:]] == ["Masuk", "Keluar"]
    assert rows[2][9] == "-2" and rows[2][11] == "Retur ke produksi"
    assert rows[1][5].startswith("'=HYPERLINK")  # formula injection dinetralkan

    summ = _read_csv(admin.get("/reports/summary.csv",
                               params={"period": "month", "date": "2026-04-15", "variant_id": vid}))  # fmt: skip
    assert summ[1][6:12] == ["0", "12", "2", "0", "0", "10"]

    stock = _read_csv(admin.get("/reports/stock.csv", params={"category_id": category["id"]}))
    assert stock[0][7] == "Stok"
    assert [r for r in stock[1:] if r[0] == p["variants"][0]["barcode"]][0][7] == "10"


def test_reports_admin_only_and_period_validation(admin: Api, staff: Api) -> None:
    for url in ("/reports/summary", "/reports/movements", "/reports/movements.csv",
                "/reports/summary.csv", "/reports/stock.csv"):  # fmt: skip
        assert staff.get(url).status_code == 403, url
    staff.ok("GET", "/dashboard")  # dashboard boleh untuk staf
    bad = [{"period": "range"}, {"period": "range", "date_from": "2026-02-01", "date_to": "2026-01-01"},
           {"period": "range", "date_from": "2024-01-01", "date_to": "2026-01-01"}]  # fmt: skip
    for params in bad:
        r = admin.get("/reports/summary", params=params)
        assert r.status_code == 422 and r.json()["code"] == "PERIOD_INVALID", params
    assert admin.get("/reports/summary", params={"period": "yearly"}).status_code == 422
    ok = admin.ok("GET", "/reports/summary", params={"period": "range", "date_from": "2026-01-01",
                                                      "date_to": date.today().isoformat()})  # fmt: skip
    assert ok["period"]["kind"] == "range"
