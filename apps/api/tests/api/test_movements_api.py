"""Alur B (barang masuk) & C (barang keluar), keranjang, idempotensi, pembatalan, kartu stok."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import psycopg
import pytest
from e2e_support import Api, create_product, post_movement, stock_of


@pytest.fixture
def product(admin: Api, category: dict[str, Any]) -> dict[str, Any]:
    return create_product(admin, category["id"])  # M=10, L=3, XL=0


def _v(product: dict[str, Any], size: str) -> dict[str, Any]:
    return next(v for v in product["variants"] if v["size"] == size)


# ----------------------------------------------------------------------------- alur B & C


def test_flow_scan_in_then_out(staff: Api, product: dict[str, Any], pg: psycopg.Connection) -> None:
    m = _v(product, "M")
    # 1) scan barcode -> konfirmasi barang
    found = staff.ok("GET", "/variants/lookup", params={"barcode": m["barcode"]})
    assert found["id"] == m["id"] and found["product_name"] == product["name"]
    # 2) masuk 5 dengan tanggal produksi & batch
    g = post_movement(staff, "IN", [{"variant_id": m["id"], "qty": 5,
                                     "production_date": "2026-11-01", "batch_code": "B-11"}]).json()  # fmt: skip
    assert g["replayed"] is False and g["type"] == "IN"
    mv = g["movements"][0]
    assert (mv["qty"], mv["balance_after"], mv["production_date"], mv["batch_code"]) == (
        5, 15, "2026-11-01", "B-11",
    )  # fmt: skip
    assert mv["user"]["id"] == staff.me["id"] and mv["source"] == "scanner"  # type: ignore[index]
    # 3) keluar 4 karena penjualan
    g = post_movement(
        staff, "OUT", [{"variant_id": m["id"], "qty": 4, "reason": "sale"}], source="camera"
    ).json()
    assert (g["movements"][0]["qty"], g["movements"][0]["balance_after"]) == (-4, 11)
    assert stock_of(staff, m["id"]) == 11
    # F-17: perangkat & waktu tercatat
    dev = pg.execute(
        "SELECT s.device_id::text FROM stock_movements m JOIN sessions s ON s.id = m.session_id"
        " WHERE m.id = %s", (g["movements"][0]["id"],),
    ).fetchone()  # fmt: skip
    assert dev == (staff.http.headers["X-Device-Id"],)


def test_out_exceeding_stock_rejected_with_clear_message(
    staff: Api, product: dict[str, Any]
) -> None:
    l_ = _v(product, "L")  # stok 3
    r = post_movement(staff, "OUT", [{"variant_id": l_["id"], "qty": 4, "reason": "sale"}])
    body = r.json()
    assert r.status_code == 409 and body["code"] == "INSUFFICIENT_STOCK"
    assert "tersedia 3" in body["message"] and "diminta 4" in body["message"]
    assert body["details"]["barcode"] == l_["barcode"]
    assert stock_of(staff, l_["id"]) == 3


def test_cart_is_all_or_nothing(staff: Api, product: dict[str, Any]) -> None:
    m, l_ = _v(product, "M"), _v(product, "L")
    r = post_movement(staff, "OUT", [
        {"variant_id": m["id"], "qty": 2, "reason": "sale"},
        {"variant_id": l_["id"], "qty": 99, "reason": "sale"},
    ])  # fmt: skip
    assert r.status_code == 409
    assert (stock_of(staff, m["id"]), stock_of(staff, l_["id"])) == (10, 3)

    g = post_movement(staff, "OUT", [
        {"variant_id": l_["id"], "qty": 1, "reason": "sale"},
        {"variant_id": m["id"], "qty": 2, "reason": "damaged"},
        {"variant_id": l_["id"], "qty": 1, "reason": "other", "note": "Sampel pameran"},
    ]).json()  # fmt: skip
    assert len(g["movements"]) == 3 and len({x["group_id"] for x in g["movements"]}) == 1
    assert (stock_of(staff, m["id"]), stock_of(staff, l_["id"])) == (8, 1)


@pytest.mark.parametrize(
    ("type_", "line", "fragment"),
    [
        ("OUT", {"qty": 1}, "alasan keluar wajib"),
        ("IN", {"qty": 1, "reason": "sale"}, "alasan hanya untuk"),
        ("OUT", {"qty": 1, "reason": "other"}, "wajib disertai catatan"),
        ("OUT", {"qty": 1, "reason": "sale", "batch_code": "B"}, "hanya untuk barang masuk"),
        ("IN", {"qty": 0}, None),
        ("IN", {"qty": -3}, None),
        ("IN", {"qty": 1, "production_date": "2999-01-01"}, "masa depan"),
        ("ADJUST", {"qty": 1}, None),
    ],
)
def test_movement_validation(
    staff: Api, product: dict[str, Any], type_: str, line: dict[str, Any], fragment: str | None
) -> None:
    r = post_movement(staff, type_, [{"variant_id": _v(product, "M")["id"], **line}])
    assert r.status_code == 422, r.text
    if fragment:
        assert fragment in r.text
    assert stock_of(staff, _v(product, "M")["id"]) == 10


def test_idempotency_key_required_and_valid(staff: Api, product: dict[str, Any]) -> None:
    body = {"type": "IN", "lines": [{"variant_id": _v(product, "M")["id"], "qty": 1}]}
    for headers in ({}, {"Idempotency-Key": "bukan-uuid"}):
        r = staff.post("/movements", json=body, headers=headers)
        assert r.status_code == 422 and r.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_double_submit_same_key_creates_one_transaction(
    staff: Api, product: dict[str, Any]
) -> None:
    m = _v(product, "M")
    key = str(uuid.uuid4())
    line = [{"variant_id": m["id"], "qty": 2}]
    first = post_movement(staff, "IN", line, key=key).json()
    again = post_movement(staff, "IN", line, key=key).json()
    assert first["replayed"] is False and again["replayed"] is True
    assert [x["id"] for x in again["movements"]] == [x["id"] for x in first["movements"]]
    assert stock_of(staff, m["id"]) == 12
    # kunci sama, isi berbeda -> ditolak
    r = post_movement(staff, "IN", [{"variant_id": m["id"], "qty": 3}], key=key)
    assert r.status_code == 409 and r.json()["code"] == "IDEMPOTENCY_MISMATCH"


def test_concurrent_double_submit_same_key(staff: Api, product: dict[str, Any]) -> None:
    """Scanner kirim Enter dua kali bersamaan: tetap satu transaksi."""
    m = _v(product, "M")
    key = str(uuid.uuid4())
    barrier = threading.Barrier(4)

    def submit(_: int) -> dict[str, Any]:
        api = Api(staff.target, ip=staff.ip)
        api.http.cookies = staff.http.cookies
        barrier.wait()
        r = post_movement(api, "IN", [{"variant_id": m["id"], "qty": 1}], key=key)
        api.close()
        assert r.status_code == 200, r.text
        return r.json()

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(submit, range(4)))
    assert sum(not r["replayed"] for r in results) == 1
    assert len({r["movements"][0]["id"] for r in results}) == 1
    assert stock_of(staff, m["id"]) == 11


def test_parallel_out_from_two_devices_never_oversells(
    make_user: Any, product: dict[str, Any]
) -> None:
    l_ = _v(product, "L")  # stok 3
    clients = [make_user("staff")[0] for _ in range(6)]
    barrier = threading.Barrier(len(clients))

    def take(api: Api) -> int:
        barrier.wait()
        return post_movement(
            api, "OUT", [{"variant_id": l_["id"], "qty": 1, "reason": "sale"}]
        ).status_code

    with ThreadPoolExecutor(len(clients)) as pool:
        codes = list(pool.map(take, clients))
    assert sorted(codes) == [200, 200, 200, 409, 409, 409]
    assert stock_of(clients[0], l_["id"]) == 0


def test_archived_variant_rejected(admin: Api, staff: Api, product: dict[str, Any]) -> None:
    m = _v(product, "M")
    admin.ok("POST", f"/variants/{m['id']}/archive")
    r = post_movement(staff, "IN", [{"variant_id": m["id"], "qty": 1}])
    assert r.status_code == 409 and r.json()["code"] == "VARIANT_ARCHIVED"
    r = post_movement(staff, "IN", [{"variant_id": 999999999, "qty": 1}])
    assert r.status_code == 404 and r.json()["code"] == "VARIANT_NOT_FOUND"


# ----------------------------------------------------------------------------- penyesuaian


def test_adjust_admin_only_with_note(admin: Api, staff: Api, product: dict[str, Any]) -> None:
    m = _v(product, "M")
    body = {"lines": [{"variant_id": m["id"], "qty": -2, "note": "Selisih hitung"}]}
    key = {"Idempotency-Key": str(uuid.uuid4())}
    r = staff.post("/movements/adjust", json=body, headers=key)
    assert r.status_code == 403
    g = admin.ok("POST", "/movements/adjust", json=body, headers=key)
    assert g["movements"][0]["type"] == "ADJUST" and stock_of(admin, m["id"]) == 8
    for bad in (
        {"variant_id": m["id"], "qty": 1, "note": "  "},
        {"variant_id": m["id"], "qty": 0, "note": "x"},
    ):
        r = admin.post("/movements/adjust", json={"lines": [bad]},
                       headers={"Idempotency-Key": str(uuid.uuid4())})  # fmt: skip
        assert r.status_code == 422
    r = admin.post("/movements/adjust",
                   json={"lines": [{"variant_id": m["id"], "qty": -100, "note": "x"}]},
                   headers={"Idempotency-Key": str(uuid.uuid4())})  # fmt: skip
    assert r.json()["code"] == "INSUFFICIENT_STOCK"


# ----------------------------------------------------------------------------- pembatalan


def _in(api: Api, vid: int, qty: int = 2) -> dict[str, Any]:
    return post_movement(api, "IN", [{"variant_id": vid, "qty": qty}]).json()["movements"][0]


def test_staff_reverses_own_recent_transaction(staff: Api, product: dict[str, Any]) -> None:
    m = _v(product, "M")
    mv = _in(staff, m["id"], 2)
    assert mv["can_reverse"] is True
    rev = staff.ok("POST", f"/movements/{mv['id']}/reverse", json={"note": "Salah scan"})
    assert (rev["type"], rev["qty"], rev["reversal_of"], rev["original_type"]) == (
        "REVERSAL", -2, mv["id"], "IN",
    )  # fmt: skip
    assert stock_of(staff, m["id"]) == 10
    orig = staff.ok("GET", f"/movements/{mv['id']}")
    assert orig["reversed_by"] == rev["id"] and orig["can_reverse"] is False
    r = staff.post(f"/movements/{mv['id']}/reverse", json={"note": "lagi"})
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_REVERSED"
    r = staff.post(f"/movements/{rev['id']}/reverse", json={"note": "x"})
    assert r.json()["code"] == "CANNOT_REVERSE_REVERSAL"


def test_staff_cannot_reverse_others_old_or_adjust(
    admin: Api, staff: Api, make_user: Any, product: dict[str, Any], pg: psycopg.Connection
) -> None:
    m = _v(product, "M")
    other, _, _ = make_user("staff")
    theirs = _in(other, m["id"])
    r = staff.post(f"/movements/{theirs['id']}/reverse", json={"note": "x"})
    assert r.status_code == 403 and r.json()["code"] == "REVERSAL_NOT_ALLOWED"

    adj = admin.ok("POST", "/movements/adjust",
                   json={"lines": [{"variant_id": m["id"], "qty": 1, "note": "x"}]},
                   headers={"Idempotency-Key": str(uuid.uuid4())})["movements"][0]  # fmt: skip
    assert staff.post(f"/movements/{adj['id']}/reverse", json={"note": "x"}).status_code == 403

    # Varian tanpa riwayat (XL) agar urutan waktu riwayat tetap konsisten setelah dimundurkan.
    mine = _in(staff, _v(product, "XL")["id"])
    # Simulasikan transaksi 16 menit lalu (trigger memaksa waktu server; ubah via replica role).
    with pg.transaction():
        pg.execute("SET LOCAL session_replication_role = replica")
        pg.execute("UPDATE stock_movements SET created_at = now() - interval '16 minutes'"
                   " WHERE id = %s", (mine["id"],))  # fmt: skip
    assert staff.ok("GET", f"/movements/{mine['id']}")["can_reverse"] is False
    assert staff.post(f"/movements/{mine['id']}/reverse", json={"note": "x"}).status_code == 403
    # Admin tetap bisa membatalkan semuanya
    admin.ok("POST", f"/movements/{mine['id']}/reverse", json={"note": "Koreksi admin"})
    admin.ok("POST", f"/movements/{adj['id']}/reverse", json={"note": "Koreksi admin"})


def test_reverse_in_after_goods_left_rejected(admin: Api, product: dict[str, Any]) -> None:
    l_ = _v(product, "L")  # 3
    mv = _in(admin, l_["id"], 5)  # 8
    post_movement(admin, "OUT", [{"variant_id": l_["id"], "qty": 7, "reason": "sale"}])  # 1
    r = admin.post(f"/movements/{mv['id']}/reverse", json={"note": "x"})
    assert r.status_code == 409 and r.json()["code"] == "INSUFFICIENT_STOCK"


def test_reverse_requires_note_and_existing(admin: Api, product: dict[str, Any]) -> None:
    mv = _in(admin, _v(product, "M")["id"])
    assert admin.post(f"/movements/{mv['id']}/reverse", json={"note": ""}).status_code == 422
    r = admin.post("/movements/999999999/reverse", json={"note": "x"})
    assert r.status_code == 404 and r.json()["code"] == "MOVEMENT_NOT_FOUND"


def test_concurrent_reversal_only_once(admin: Api, product: dict[str, Any]) -> None:
    mv = _in(admin, _v(product, "M")["id"], 3)
    barrier = threading.Barrier(4)

    def rev(_: int) -> int:
        api = Api(admin.target, ip=admin.ip)
        api.http.cookies = admin.http.cookies
        barrier.wait()
        code = api.post(f"/movements/{mv['id']}/reverse", json={"note": "x"}).status_code
        api.close()
        return code

    with ThreadPoolExecutor(4) as pool:
        codes = list(pool.map(rev, range(4)))
    assert sorted(codes) == [200, 409, 409, 409]
    assert stock_of(admin, _v(product, "M")["id"]) == 10


# ----------------------------------------------------------------------------- riwayat


def test_staff_sees_only_own_movements(admin: Api, staff: Api, product: dict[str, Any]) -> None:
    m = _v(product, "M")
    mine = _in(staff, m["id"])
    page = staff.ok("GET", "/movements", params={"variant_id": m["id"]})
    assert [x["id"] for x in page["items"]] == [mine["id"]]  # stok awal milik admin tidak terlihat
    everything = admin.ok("GET", "/movements", params={"variant_id": m["id"]})
    assert everything["total"] == 2
    initial = next(x for x in everything["items"] if x["id"] != mine["id"])
    assert staff.get(f"/movements/{initial['id']}").status_code == 404
    typed = admin.ok("GET", "/movements", params={"variant_id": m["id"], "type": ["IN"]})
    assert typed["total"] == 2


def test_stock_card(admin: Api, product: dict[str, Any]) -> None:
    m = _v(product, "M")
    post_movement(admin, "IN", [{"variant_id": m["id"], "qty": 5}])
    out = post_movement(admin, "OUT", [{"variant_id": m["id"], "qty": 3, "reason": "sale"}]).json()
    admin.ok("POST", f"/movements/{out['movements'][0]['id']}/reverse", json={"note": "batal"})
    card = admin.ok("GET", f"/variants/{m['id']}/stock-card")
    assert card["opening_balance"] == 0 and card["closing_balance"] == card["current_stock"] == 15
    assert (card["total_in"], card["total_out"], card["total_reversal"]) == (15, 3, 3)
    balances = [x["balance_after"] for x in card["movements"]]
    assert balances == [10, 15, 12, 15]
    assert [x["type"] for x in card["movements"]] == ["IN", "IN", "OUT", "REVERSAL"]
    r = admin.get(f"/variants/{m['id']}/stock-card",
                  params={"date_from": "2026-12-01", "date_to": "2026-11-01"})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "PERIOD_INVALID"
