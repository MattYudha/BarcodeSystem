"""F-13 stock opname via API."""

from typing import Any

import psycopg
import pytest
from e2e_support import Api, create_product, post_movement, stock_of


@pytest.fixture
def opname(admin: Api, pg: psycopg.Connection) -> dict[str, Any]:
    # Hanya boleh satu draft; tutup draft sisa test lain.
    pg.execute(
        "UPDATE stock_opnames SET status = 'cancelled', cancelled_at = now() WHERE status = 'draft'"
    )
    return admin.ok("POST", "/opnames", 201, json={"note": "Opname akhir bulan"})


@pytest.fixture
def product(admin: Api, category: dict[str, Any]) -> dict[str, Any]:
    return create_product(admin, category["id"])  # M=10, L=3, XL=0


def _v(product: dict[str, Any], size: str) -> dict[str, Any]:
    return next(v for v in product["variants"] if v["size"] == size)


def test_full_opname_flow(admin: Api, opname: dict[str, Any], product: dict[str, Any]) -> None:
    m, l_, xl = _v(product, "M"), _v(product, "L"), _v(product, "XL")
    assert opname["status"] == "draft" and opname["code"].startswith("SO-")
    # hitung via scan (+1 per scan) dan via ketik jumlah
    for _ in range(3):
        item = admin.ok(
            "POST", f"/opnames/{opname['id']}/scan", json={"barcode": l_["barcode"].lower()}
        )
    assert (item["counted_qty"], item["current_stock"], item["diff"]) == (3, 3, 0)
    o = admin.ok("PUT", f"/opnames/{opname['id']}/items", json={"items": [
        {"variant_id": m["id"], "counted_qty": 8},
        {"variant_id": xl["id"], "counted_qty": 2},
    ]})  # fmt: skip
    assert o["item_count"] == 3 and o["diff_count"] == 2

    # Ada transaksi masuk saat opname berlangsung: selisih dihitung terhadap stok SAAT finalize.
    post_movement(admin, "IN", [{"variant_id": m["id"], "qty": 1}])  # M = 11
    final = admin.ok("POST", f"/opnames/{opname['id']}/finalize")
    assert final["status"] == "finalized" and final["finalized_by"]["id"] == admin.me["id"]  # type: ignore[index]
    by_size = {i["variant"]["size"]: i for i in final["items"]}
    assert (by_size["M"]["current_stock"], by_size["M"]["diff"]) == (11, -3)
    assert (by_size["XL"]["current_stock"], by_size["XL"]["diff"]) == (0, 2)
    assert by_size["L"]["diff"] == 0
    assert (stock_of(admin, m["id"]), stock_of(admin, l_["id"]), stock_of(admin, xl["id"])) == (
        8,
        3,
        2,
    )

    adjust = admin.ok("GET", "/movements", params={"product_id": product["id"], "type": ["ADJUST"]})
    assert adjust["total"] == 2  # L tanpa selisih tidak dibuatkan transaksi
    assert {x["note"] for x in adjust["items"]} == {f"Stock opname {opname['code']}"}
    assert {x["source"] for x in adjust["items"]} == {"opname"}

    # klik ganda finalize -> hasil sama, tidak ada penyesuaian ganda
    again = admin.ok("POST", f"/opnames/{opname['id']}/finalize")
    assert again["status"] == "finalized"
    assert stock_of(admin, m["id"]) == 8
    # terkunci setelah final
    r = admin.put(f"/opnames/{opname['id']}/items",
                  json={"items": [{"variant_id": m["id"], "counted_qty": 1}]})  # fmt: skip
    assert r.status_code == 409 and r.json()["code"] == "OPNAME_CLOSED"
    assert admin.post(f"/opnames/{opname['id']}/cancel").json()["code"] == "OPNAME_CLOSED"


def test_single_draft_and_cancel(admin: Api, opname: dict[str, Any]) -> None:
    r = admin.post("/opnames", json={})
    assert r.status_code == 409 and r.json()["code"] == "OPNAME_DRAFT_EXISTS"
    c = admin.ok("POST", f"/opnames/{opname['id']}/cancel")
    assert c["status"] == "cancelled"
    assert admin.ok("POST", f"/opnames/{opname['id']}/cancel")["status"] == "cancelled"
    assert admin.post(f"/opnames/{opname['id']}/finalize").json()["code"] == "OPNAME_CLOSED"
    admin.ok("POST", "/opnames", 201, json={})  # draft baru boleh setelah dibatalkan


def test_opname_errors(admin: Api, opname: dict[str, Any], product: dict[str, Any]) -> None:
    oid = opname["id"]
    assert admin.post(f"/opnames/{oid}/finalize").json()["code"] == "OPNAME_EMPTY"
    r = admin.post(f"/opnames/{oid}/scan", json={"barcode": "BHV-0000-00"})
    assert r.status_code == 404 and r.json()["code"] == "VARIANT_NOT_FOUND"
    r = admin.put(
        f"/opnames/{oid}/items", json={"items": [{"variant_id": 999999999, "counted_qty": 1}]}
    )
    assert r.status_code == 404
    r = admin.put(
        f"/opnames/{oid}/items",
        json={"items": [{"variant_id": _v(product, "M")["id"], "counted_qty": -1}]},
    )
    assert r.status_code == 422
    assert (
        admin.delete(f"/opnames/{oid}/items/{_v(product, 'M')['id']}").json()["code"]
        == "OPNAME_ITEM_NOT_FOUND"
    )
    admin.ok("POST", f"/opnames/{oid}/scan", json={"barcode": _v(product, "M")["barcode"]})
    admin.ok("DELETE", f"/opnames/{oid}/items/{_v(product, 'M')['id']}", 204)
    assert admin.ok("GET", f"/opnames/{oid}")["item_count"] == 0
    assert admin.get("/opnames/999999999").json()["code"] == "OPNAME_NOT_FOUND"


def test_staff_cannot_use_opname(staff: Api, opname: dict[str, Any]) -> None:
    for method, url in (("GET", "/opnames"), ("POST", "/opnames"), ("GET", f"/opnames/{opname['id']}"),
                        ("POST", f"/opnames/{opname['id']}/finalize")):  # fmt: skip
        assert staff.http.request(method, url, json={}).status_code == 403


def test_list_opnames(admin: Api, opname: dict[str, Any]) -> None:
    drafts = admin.ok("GET", "/opnames", params={"status": "draft"})
    assert [o["id"] for o in drafts] == [opname["id"]]
    assert opname["id"] in [o["id"] for o in admin.ok("GET", "/opnames")]
