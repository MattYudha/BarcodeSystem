"""F-02 kelola akun staf + hak akses peran."""

import uuid
from typing import Any

from e2e_support import Api, Target, unique


def test_admin_creates_staff_with_temp_password(admin: Api, target: Target) -> None:
    email = f"{uuid.uuid4().hex[:10]}@bhavia-e2e.com"
    user = admin.ok("POST", "/users", 201, json={"name": "Budi", "email": email})
    assert user["role"] == "staff" and user["must_change_password"] is True
    temp = user["temp_password"]
    assert temp and len(temp) >= 12

    api = Api(target)
    me = api.login(email, temp).json()
    assert me["must_change_password"] is True
    # Selama belum ganti password: hanya /auth/* yang boleh.
    r = api.get("/products")
    assert r.status_code == 403 and r.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    api.ok("GET", "/auth/me")
    api.ok("POST", "/auth/change-password", 204,
           json={"current_password": temp, "new_password": "PasswordBaru9"})  # fmt: skip
    api.ok("GET", "/products")
    api.close()


def test_duplicate_email_rejected(admin: Api) -> None:
    email = f"{uuid.uuid4().hex[:10]}@bhavia-e2e.com"
    admin.ok("POST", "/users", 201, json={"name": "A", "email": email, "password": "Rahasia123"})
    r = admin.post("/users", json={"name": "B", "email": email.upper(), "password": "Rahasia123"})
    assert r.status_code == 409 and r.json()["code"] == "EMAIL_TAKEN"


def test_invalid_user_payloads(admin: Api) -> None:
    for body in (
        {"name": "A", "email": "bukan-email"},
        {"name": "", "email": "a@bhavia-e2e.com"},
        {"name": "A", "email": "a@bhavia-e2e.com", "role": "superadmin"},
        {"name": "A", "email": "a@bhavia-e2e.com", "password": "123"},
        {"name": "A", "email": "a@bhavia-e2e.com", "extra": 1},
    ):
        r = admin.post("/users", json=body)
        assert r.status_code == 422, body
        assert r.json()["code"] == "VALIDATION_ERROR"


def test_staff_forbidden_on_admin_endpoints(staff: Api, admin: Api) -> None:
    cat = admin.ok("POST", "/categories", 201, json={"name": unique("Kat")})
    checks = [
        ("GET", "/users", None),
        ("POST", "/users", {"name": "X", "email": "x@bhavia-e2e.com"}),
        ("PATCH", "/users/1", {"name": "X"}),
        ("POST", "/users/1/reset-password", None),
        ("POST", "/categories", {"name": "X"}),
        ("PATCH", f"/categories/{cat['id']}", {"name": "X"}),
        ("POST", f"/categories/{cat['id']}/archive", None),
        ("POST", "/products", {"category_id": cat["id"], "name": "X",
                               "variants": [{"size": "M"}]}),
        ("PATCH", "/products/1", {"name": "X"}),
        ("POST", "/products/1/archive", None),
        ("DELETE", "/products/1", None),
        ("POST", "/products/1/variants", {"size": "M"}),
        ("PATCH", "/variants/1", {"min_stock": 1}),
        ("POST", "/variants/1/archive", None),
    ]  # fmt: skip
    for method, url, body in checks:
        r = staff.http.request(method, url, json=body)
        assert r.status_code == 403, f"{method} {url} -> {r.status_code}"
        assert r.json()["code"] == "FORBIDDEN"


def test_staff_can_read_catalog(staff: Api) -> None:
    staff.ok("GET", "/products")
    staff.ok("GET", "/variants")
    staff.ok("GET", "/categories")


def test_deactivate_revokes_sessions_immediately(admin: Api, make_user: Any) -> None:
    api, user, _ = make_user("staff")
    api.ok("GET", "/auth/me")
    admin.ok("PATCH", f"/users/{user['id']}", json={"is_active": False})
    assert api.get("/auth/me").status_code == 401


def test_reset_password_revokes_and_forces_change(
    admin: Api, make_user: Any, target: Target
) -> None:
    api, user, old = make_user("staff")
    temp = admin.ok("POST", f"/users/{user['id']}/reset-password")["temp_password"]
    assert api.get("/auth/me").status_code == 401
    fresh = Api(target)
    fresh.login(user["email"], old, expect=401)
    assert fresh.login(user["email"], temp).json()["must_change_password"] is True
    fresh.close()


def test_admin_cannot_modify_self(admin: Api) -> None:
    me = admin.ok("GET", "/auth/me")
    for body in ({"role": "staff"}, {"is_active": False}):
        r = admin.patch(f"/users/{me['id']}", json=body)
        assert r.status_code == 409 and r.json()["code"] == "CANNOT_MODIFY_SELF"
    assert admin.post(f"/users/{me['id']}/reset-password").json()["code"] == "CANNOT_MODIFY_SELF"
    # nama sendiri boleh diubah
    assert admin.ok("PATCH", f"/users/{me['id']}", json={"name": me["name"]})["name"] == me["name"]


def test_promote_and_demote_admin(admin: Api, make_user: Any) -> None:
    api, user, _ = make_user("staff")
    assert api.get("/users").status_code == 403
    admin.ok("PATCH", f"/users/{user['id']}", json={"role": "admin"})
    api.ok("GET", "/users")  # peran dibaca ulang tiap request
    admin.ok("PATCH", f"/users/{user['id']}", json={"role": "staff"})
    assert api.get("/users").status_code == 403


def test_unknown_user(admin: Api) -> None:
    r = admin.patch("/users/999999999", json={"name": "x"})
    assert r.status_code == 404 and r.json()["code"] == "USER_NOT_FOUND"


def test_audit_log_written(admin: Api, make_user: Any, pg: Any) -> None:
    _, user, _ = make_user("staff", login=False)
    admin.ok("PATCH", f"/users/{user['id']}", json={"is_active": False})
    actions = [
        r[0]
        for r in pg.execute(
            "SELECT action FROM audit_logs WHERE entity_type = 'user' AND entity_id = %s ORDER BY id",
            (user["id"],),
        ).fetchall()
    ]
    assert actions == ["user.create", "user.update"]
