"""Regresi: null eksplisit pada field opsional tidak boleh menyebabkan 500.

Bug nyata yang ditemukan E2E web: `Annotated[str | None, Field(max_length=n)]` membuat Pydantic
menghitung len(None) -> TypeError -> HTTP 500 saat UI mengirim `"color": null`.
"""

import uuid
from typing import Any

from e2e_support import Api, create_product, post_movement


def test_explicit_nulls_accepted_everywhere(admin: Api, category: dict[str, Any]) -> None:
    p = admin.ok("POST", "/products", 201, json={
        "category_id": category["id"], "name": "Null Safe", "description": None, "price": None,
        "variants": [{"size": "M", "color": None, "min_stock": 0, "initial_stock": 3,
                      "production_date": None, "batch_code": None}],
    })  # fmt: skip
    assert p["description"] is None and p["variants"][0]["color"] is None
    admin.ok("PATCH", f"/products/{p['id']}", json={"description": None, "price": None})
    v = admin.ok("POST", f"/products/{p['id']}/variants", 201,
                 json={"size": "L", "color": None, "batch_code": None, "production_date": None})  # fmt: skip
    admin.ok("PATCH", f"/variants/{v['id']}", json={"color": None})
    vid = p["variants"][0]["id"]
    r = post_movement(admin, "IN", [{"variant_id": vid, "qty": 1, "note": None,
                                     "batch_code": None, "production_date": None}])  # fmt: skip
    assert r.status_code == 200, r.text
    r = post_movement(admin, "OUT", [{"variant_id": vid, "qty": 1, "reason": "sale", "note": None}])
    assert r.status_code == 200, r.text


def test_login_with_null_device_label(admin: Api) -> None:
    me = admin.ok("GET", "/auth/me")
    assert me["email"]
    r = admin.post(
        "/auth/login", json={"email": "x@bhavia-e2e.com", "password": "x", "device_label": None}
    )
    assert r.status_code == 401  # bukan 500


def test_too_long_text_is_422_not_500(admin: Api, category: dict[str, Any]) -> None:
    r = admin.post("/products", json={
        "category_id": category["id"], "name": "X", "variants": [{"size": "M", "color": "x" * 41}],
    })  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    p = create_product(admin, category["id"])
    r = post_movement(
        admin, "IN", [{"variant_id": p["variants"][0]["id"], "qty": 1, "note": "x" * 501}]
    )
    assert r.status_code == 422


def test_wrong_json_types_are_422_not_500(admin: Api, category: dict[str, Any]) -> None:
    bad_bodies: list[tuple[str, str, Any]] = [
        ("POST", "/products", {"category_id": "abc", "name": 5, "variants": "x"}),
        (
            "POST",
            "/products",
            {"category_id": category["id"], "name": "X", "variants": [{"size": None}]},
        ),
        ("POST", "/products", None),
        ("POST", "/categories", {"name": None}),
        ("POST", "/users", {"name": None, "email": None}),
        ("POST", "/auth/login", {"email": None, "password": None}),
        ("POST", "/movements/adjust", {"lines": [{"variant_id": 1, "qty": "x", "note": None}]}),
    ]
    for method, url, body in bad_bodies:
        r = admin.http.request(
            method, url, json=body, headers={"Idempotency-Key": str(uuid.uuid4())}
        )
        assert r.status_code == 422, f"{method} {url} {body} -> {r.status_code} {r.text}"
