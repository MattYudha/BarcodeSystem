"""F-06 barcode Code 128 + F-08 cetak label (A4 & thermal)."""

import re
from typing import Any

import pytest
from e2e_support import Api, create_product


@pytest.fixture
def product(admin: Api, category: dict[str, Any]) -> dict[str, Any]:
    return create_product(admin, category["id"])


def _pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def test_barcode_svg(staff: Api, product: dict[str, Any]) -> None:
    v = product["variants"][0]
    r = staff.get(f"/variants/{v['id']}/barcode.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "immutable" in r.headers["cache-control"]
    assert b"<svg" in r.content and v["barcode"].encode() in r.content


@pytest.mark.parametrize(
    ("template", "copies", "pages"),
    [("a4_3x8", 25, 2), ("a4_4x10", 40, 1), ("thermal_50x30", 3, 3), ("thermal_40x30", 2, 2)],
)
def test_label_pdf_templates(
    staff: Api, product: dict[str, Any], template: str, copies: int, pages: int
) -> None:
    r = staff.post("/labels/pdf", json={
        "template": template, "show_price": True,
        "items": [{"variant_id": product["variants"][0]["id"], "copies": copies}],
    })  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert _pages(r.content) == pages


def test_label_start_position_skips_used_stickers(staff: Api, product: dict[str, Any]) -> None:
    vid = product["variants"][0]["id"]
    body = {"template": "a4_3x8", "items": [{"variant_id": vid, "copies": 3}], "start_position": 23}
    r = staff.post("/labels/pdf", json=body)
    assert _pages(r.content) == 2  # slot 23, 24 di halaman 1, sisanya halaman 2


def test_bulk_labels_multiple_variants(staff: Api, product: dict[str, Any]) -> None:
    items = [{"variant_id": v["id"], "copies": 8} for v in product["variants"]]
    r = staff.post("/labels/pdf", json={"template": "a4_3x8", "items": items})
    assert r.status_code == 200 and _pages(r.content) == 1


def test_label_limits_and_unknown_variant(staff: Api, product: dict[str, Any]) -> None:
    vid = product["variants"][0]["id"]
    r = staff.post("/labels/pdf", json={"items": [{"variant_id": vid, "copies": 500}] * 5})
    assert r.status_code == 422 and r.json()["code"] == "LABEL_LIMIT"
    r = staff.post("/labels/pdf", json={"items": [{"variant_id": 999999999}]})
    assert r.status_code == 404 and r.json()["code"] == "VARIANT_NOT_FOUND"
    r = staff.post("/labels/pdf", json={"template": "a5", "items": [{"variant_id": vid}]})
    assert r.status_code == 422


def test_label_print_audited(staff: Api, product: dict[str, Any], pg: Any) -> None:
    vid = product["variants"][0]["id"]
    staff.ok("POST", "/labels/pdf", json={"items": [{"variant_id": vid, "copies": 2}]})
    row = pg.execute(
        "SELECT after->>'total' FROM audit_logs WHERE action = 'label.print'"
        " AND actor_id = %s ORDER BY id DESC LIMIT 1",
        (staff.me["id"] if staff.me else 0,),
    ).fetchone()
    assert row == ("2",)
