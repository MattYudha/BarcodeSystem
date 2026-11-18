"""Alur A (tambah barang + varian + stok awal), F-05/F-06/F-07, arsip, barcode lookup."""

import re
from typing import Any

from e2e_support import Api, create_product, unique


def _variant(product: dict[str, Any], size: str) -> dict[str, Any]:
    return next(v for v in product["variants"] if v["size"] == size)


def test_create_product_with_variants_and_initial_stock(
    admin: Api, category: dict[str, Any], pg: Any
) -> None:
    p = create_product(admin, category["id"])
    assert re.fullmatch(r"BHV-\d{4,}", p["code"])
    assert [v["barcode"] for v in p["variants"]] == [f"{p['code']}-0{i}" for i in (1, 2, 3)]
    assert p["variant_count"] == 3 and p["total_stock"] == 13
    assert p["price"] == 185000 and p["category"]["id"] == category["id"]
    m, l_, xl = _variant(p, "M"), _variant(p, "L"), _variant(p, "XL")
    assert (m["stock"], m["stock_status"], m["is_alert"]) == (10, "ok", False)
    assert (l_["stock"], l_["stock_status"], l_["is_alert"]) == (3, "low", True)
    assert (xl["stock"], xl["stock_status"], xl["is_alert"]) == (0, "out", False)
    assert p["alert_count"] == 1 and p["has_movements"] is True

    # Temuan prototipe #1: stok awal tercatat sebagai transaksi IN "Stok awal".
    rows = pg.execute(
        "SELECT variant_id, type::text, qty, note, source::text FROM stock_movements"
        " WHERE variant_id = ANY(%s) ORDER BY variant_id",
        ([v["id"] for v in p["variants"]],),
    ).fetchall()
    assert rows == [
        (m["id"], "IN", 10, "Stok awal", "initial"),
        (l_["id"], "IN", 3, "Stok awal", "initial"),
    ]


def test_input_normalization(admin: Api, category: dict[str, Any]) -> None:
    p = create_product(admin, category["id"], name="  Gamis   Brokat  ",
                       variants=[{"size": " xl ", "color": "  Hijau   Botol "}])  # fmt: skip
    assert p["name"] == "Gamis Brokat"
    assert (p["variants"][0]["size"], p["variants"][0]["color"]) == ("XL", "Hijau Botol")


def test_duplicate_variants_rejected(admin: Api, category: dict[str, Any]) -> None:
    r = admin.post("/products", json={
        "category_id": category["id"], "name": "X",
        "variants": [{"size": "M", "color": "merah"}, {"size": "m", "color": "Merah"}],
    })  # fmt: skip
    assert r.status_code == 422
    p = create_product(admin, category["id"])
    r = admin.post(f"/products/{p['id']}/variants", json={"size": "m", "color": "MERAH"})
    assert r.status_code == 409 and r.json()["code"] == "VARIANT_DUPLICATE"
    r = admin.post(f"/products/{p['id']}/variants", json={"size": "XL"})  # XL tanpa warna sudah ada
    assert r.json()["code"] == "VARIANT_DUPLICATE"


def test_invalid_product_payloads(admin: Api, category: dict[str, Any]) -> None:
    base = {"category_id": category["id"], "name": "X", "variants": [{"size": "M"}]}
    bad = [
        {**base, "variants": []},
        {**base, "name": "   "},
        {**base, "price": -1},
        {**base, "variants": [{"size": "M", "initial_stock": -1}]},
        {**base, "variants": [{"size": "M", "min_stock": -1}]},
        {**base, "variants": [{"size": "M", "initial_stock": 1, "production_date": "2999-01-01"}]},
        {**base, "variants": [{"size": "M", "batch_code": "B1"}]},  # batch tanpa stok awal
    ]
    for body in bad:
        r = admin.post("/products", json=body)
        assert r.status_code == 422, body
    r = admin.post("/products", json={**base, "category_id": 999999999})
    assert r.status_code == 404 and r.json()["code"] == "CATEGORY_NOT_FOUND"


def test_product_create_is_atomic(admin: Api, category: dict[str, Any]) -> None:
    """Kategori arsip -> tidak ada produk setengah jadi."""
    name = unique("Atomic")
    admin.ok("POST", f"/categories/{category['id']}/archive")
    r = admin.post("/products", json={"category_id": category["id"], "name": name,
                                      "variants": [{"size": "M", "initial_stock": 5}]})  # fmt: skip
    assert r.status_code == 409 and r.json()["code"] == "CATEGORY_ARCHIVED"
    assert admin.ok("GET", "/products", params={"q": name, "archived": "all"})["total"] == 0


def test_rename_keeps_barcode(admin: Api, category: dict[str, Any]) -> None:
    p = create_product(admin, category["id"])
    upd = admin.ok("PATCH", f"/products/{p['id']}", json={"name": "Nama Baru", "price": None})
    assert upd["name"] == "Nama Baru" and upd["price"] is None
    assert [v["barcode"] for v in upd["variants"]] == [v["barcode"] for v in p["variants"]]
    assert upd["code"] == p["code"]


def test_barcode_and_code_cannot_be_set_by_client(admin: Api, category: dict[str, Any]) -> None:
    r = admin.post("/products", json={"category_id": category["id"], "name": "X", "code": "BHV-1",
                                      "variants": [{"size": "M"}]})  # fmt: skip
    assert r.status_code == 422  # field tak dikenal ditolak
    p = create_product(admin, category["id"])
    r = admin.patch(f"/variants/{p['variants'][0]['id']}", json={"barcode": "BHV-9999-99"})
    assert r.status_code == 422


def test_variant_identity_locked_after_movements(admin: Api, category: dict[str, Any]) -> None:
    p = create_product(admin, category["id"])
    m, xl = _variant(p, "M"), _variant(p, "XL")
    r = admin.patch(f"/variants/{m['id']}", json={"size": "S"})
    assert r.status_code == 409 and r.json()["code"] == "VARIANT_HAS_MOVEMENTS"
    assert (
        admin.ok("PATCH", f"/variants/{m['id']}", json={"min_stock": 20})["stock_status"] == "low"
    )
    # Belum ada transaksi -> boleh koreksi ukuran/warna (barcode tetap).
    upd = admin.ok("PATCH", f"/variants/{xl['id']}", json={"size": "xxl", "color": "Biru"})
    assert (upd["size"], upd["color"], upd["barcode"]) == ("XXL", "Biru", xl["barcode"])


def test_search_and_filters(admin: Api, category: dict[str, Any]) -> None:
    tag = unique("Celana Bahan").split()[-1]
    p = create_product(admin, category["id"], name=f"Celana Bahan {tag}")
    other_cat = admin.ok("POST", "/categories", 201, json={"name": unique("Blazer")})
    create_product(admin, other_cat["id"], name=f"Blazer {tag}")

    assert admin.ok("GET", "/products", params={"q": tag})["total"] == 2
    res = admin.ok("GET", "/products", params={"q": tag, "category_id": category["id"]})
    assert [x["id"] for x in res["items"]] == [p["id"]]
    assert admin.ok("GET", "/products", params={"q": p["code"]})["total"] == 1
    assert admin.ok("GET", "/products", params={"q": p["variants"][1]["barcode"]})["total"] == 1
    assert admin.ok("GET", "/products", params={"q": "%"})["total"] >= 0  # wildcard di-escape

    v = admin.ok("GET", "/variants", params={"q": tag, "category_id": category["id"]})
    assert v["total"] == 3
    assert [x["size"] for x in admin.ok("GET", "/variants",
            params={"q": tag, "stock_status": "alert"})["items"]] == ["L", "L"]  # fmt: skip
    out = admin.ok("GET", "/variants", params={"q": tag, "stock_status": "out"})["items"]
    assert {x["size"] for x in out} == {"XL"}
    assert admin.ok("GET", "/variants", params={"q": tag, "size": "m"})["total"] == 2
    paged = admin.ok("GET", "/variants", params={"q": tag, "page_size": 2, "page": 3})
    assert paged["total"] == 6 and len(paged["items"]) == 2
    assert admin.get("/variants", params={"stock_status": "bogus"}).status_code == 422


def test_archive_hides_from_scan_and_lists(
    admin: Api, staff: Api, category: dict[str, Any]
) -> None:
    p = create_product(admin, category["id"])
    m = _variant(p, "M")
    assert staff.ok("GET", "/variants/lookup", params={"barcode": m["barcode"]})["id"] == m["id"]

    admin.ok("POST", f"/products/{p['id']}/archive")
    r = staff.get("/variants/lookup", params={"barcode": m["barcode"]})
    assert r.status_code == 409 and r.json()["code"] == "VARIANT_ARCHIVED"
    assert admin.ok("GET", "/products", params={"q": p["code"]})["total"] == 0
    assert (
        admin.ok("GET", "/products", params={"q": p["code"], "archived": "archived"})["total"] == 1
    )
    r = admin.post(f"/products/{p['id']}/variants", json={"size": "S"})
    assert r.json()["code"] == "PRODUCT_ARCHIVED"
    r = admin.post(f"/variants/{m['id']}/unarchive")
    assert r.json()["code"] == "PRODUCT_ARCHIVED"

    admin.ok("POST", f"/products/{p['id']}/unarchive")
    admin.ok("POST", f"/variants/{m['id']}/archive")
    assert staff.get("/variants/lookup", params={"barcode": m["barcode"]}).status_code == 409
    admin.ok("POST", f"/variants/{m['id']}/unarchive")
    staff.ok("GET", "/variants/lookup", params={"barcode": m["barcode"]})


def test_lookup_normalizes_and_rejects_unknown(
    staff: Api, admin: Api, category: dict[str, Any]
) -> None:
    p = create_product(admin, category["id"])
    code = p["variants"][0]["barcode"]
    assert (
        staff.ok("GET", "/variants/lookup", params={"barcode": f"  {code.lower()} "})["barcode"]
        == code
    )
    r = staff.get("/variants/lookup", params={"barcode": "BHV-0000-00"})
    assert r.status_code == 404 and r.json()["code"] == "VARIANT_NOT_FOUND"
    assert "dikenal" in r.json()["message"]


def test_delete_only_without_movements(admin: Api, category: dict[str, Any]) -> None:
    with_stock = create_product(admin, category["id"])
    r = admin.delete(f"/products/{with_stock['id']}")
    assert r.status_code == 409 and r.json()["code"] == "PRODUCT_HAS_MOVEMENTS"

    empty = create_product(admin, category["id"], variants=[{"size": "M"}, {"size": "L"}])
    assert empty["has_movements"] is False
    admin.ok("DELETE", f"/products/{empty['id']}", 204)
    assert admin.get(f"/products/{empty['id']}").json()["code"] == "PRODUCT_NOT_FOUND"


def test_categories_crud(admin: Api, staff: Api) -> None:
    name = unique("Kemeja")
    cat = admin.ok("POST", "/categories", 201, json={"name": name})
    r = admin.post("/categories", json={"name": name.upper()})
    assert r.status_code == 409 and r.json()["code"] == "CATEGORY_TAKEN"
    renamed = admin.ok("PATCH", f"/categories/{cat['id']}", json={"name": name + " Pria"})
    assert renamed["name"] == name + " Pria"
    admin.ok("POST", f"/categories/{cat['id']}/archive")
    assert cat["id"] not in [c["id"] for c in staff.ok("GET", "/categories")]
    assert cat["id"] in [c["id"] for c in staff.ok("GET", "/categories",
                                                   params={"include_archived": True})]  # fmt: skip
    admin.ok("POST", f"/categories/{cat['id']}/unarchive")


def test_error_format_consistent(admin: Api) -> None:
    for r in (admin.get("/products/999999999"), admin.get("/nope"), admin.get("/variants/abc")):
        body = r.json()
        assert set(body) == {"code", "message", "details"}, body
