"""F-01 login/logout/sesi, pembatasan percobaan login, CSRF, ganti password."""

import uuid
from typing import Any

import psycopg
from e2e_support import ALLOWED_ORIGIN, Api, Target


def test_login_me_logout(admin: Api, target: Target) -> None:
    me = admin.ok("GET", "/auth/me")
    assert me["email"] == target.admin_email and me["role"] == "admin"
    admin.ok("POST", "/auth/logout", 204)
    r = admin.get("/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"


def test_cookie_flags(target: Target) -> None:
    api = Api(target)
    r = api.login(target.admin_email, target.admin_password)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    api.close()


def test_unauthenticated_requests_rejected(anon: Api) -> None:
    for url in ("/auth/me", "/products", "/variants", "/categories", "/users"):
        r = anon.get(url)
        assert r.status_code == 401, url
        assert r.json()["code"] == "UNAUTHENTICATED"


def test_wrong_password_same_error_as_unknown_email(anon: Api, target: Target) -> None:
    a = anon.login(target.admin_email, "salah-banget", expect=401).json()
    b = anon.login(f"{uuid.uuid4().hex}@nowhere-e2e.com", "salah-banget", expect=401).json()
    assert a["code"] == b["code"] == "INVALID_CREDENTIALS"
    assert a["message"] == b["message"]


def test_email_is_case_insensitive(make_user: Any, target: Target) -> None:
    _, user, password = make_user("staff", login=False)
    api = Api(target)
    api.login(user["email"].upper(), password)
    api.close()


def test_lockout_after_5_failures_then_correct_password_blocked(
    make_user: Any, target: Target
) -> None:
    _, user, password = make_user("staff", login=False)
    api = Api(target)
    for _ in range(5):
        api.login(user["email"], "salah-123", expect=401)
    r = api.login(user["email"], password, expect=429)
    assert r.json()["code"] == "LOGIN_LOCKED"
    assert int(r.headers["retry-after"]) > 0
    api.close()


def test_success_resets_failure_counter(make_user: Any, target: Target) -> None:
    _, user, password = make_user("staff", login=False)
    api = Api(target)
    for _ in range(4):
        api.login(user["email"], "salah-123", expect=401)
    api.login(user["email"], password)
    for _ in range(4):
        api.login(user["email"], "salah-123", expect=401)
    api.login(user["email"], password)  # belum terkunci: hitungan direset oleh login sukses
    api.close()


def test_ip_lockout_after_20_failures(target: Target) -> None:
    api = Api(target)  # IP palsu unik
    for i in range(20):
        api.login(f"spray{i}-{uuid.uuid4().hex[:6]}@bhavia-e2e.com", "x", expect=401)
    r = api.login(target.admin_email, target.admin_password, expect=429)
    assert r.json()["code"] == "LOGIN_LOCKED"
    # IP lain tidak terpengaruh
    other = Api(target)
    other.login(target.admin_email, target.admin_password)
    api.close()
    other.close()


def test_inactive_account_cannot_login(admin: Api, make_user: Any, target: Target) -> None:
    _, user, password = make_user("staff", login=False)
    admin.ok("PATCH", f"/users/{user['id']}", json={"is_active": False})
    api = Api(target)
    assert api.login(user["email"], password, expect=403).json()["code"] == "ACCOUNT_INACTIVE"
    api.close()


def test_csrf_foreign_origin_rejected(admin: Api) -> None:
    r = admin.post("/categories", json={"name": "x"}, headers={"Origin": "https://evil.test"})
    assert r.status_code == 403 and r.json()["code"] == "CSRF_REJECTED"
    r = admin.post(
        "/categories",
        json={"name": f"Ok {uuid.uuid4().hex[:6]}"},
        headers={"Origin": ALLOWED_ORIGIN},
    )
    assert r.status_code == 201


def test_idle_timeout(admin: Api, pg: psycopg.Connection) -> None:
    pg.execute(
        "UPDATE sessions SET last_seen_at = now() - interval '31 minutes'"
        " WHERE user_id = %s AND revoked_at IS NULL AND ip = %s",
        (admin.me["id"] if admin.me else 0, admin.ip),
    )
    r = admin.get("/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "SESSION_EXPIRED"
    assert admin.get("/auth/me").json()["code"] == "UNAUTHENTICATED"  # sesi sudah dicabut


def test_session_records_device(admin: Api, pg: psycopg.Connection) -> None:
    row = pg.execute(
        "SELECT device_id::text, host(ip), user_agent FROM sessions"
        " WHERE ip = %s AND revoked_at IS NULL",
        (admin.ip,),
    ).fetchone()
    assert row is not None
    assert row[0] == admin.http.headers["X-Device-Id"]
    assert row[1] == admin.ip
    assert row[2]


def test_change_password_flow(make_user: Any, target: Target) -> None:
    api, user, password = make_user("staff")
    other_device = Api(target)
    other_device.login(user["email"], password)

    r = api.post(
        "/auth/change-password", json={"current_password": "salah", "new_password": "BaruBanget1"}
    )
    assert r.status_code == 422 and r.json()["code"] == "WRONG_PASSWORD"
    r = api.post(
        "/auth/change-password", json={"current_password": password, "new_password": password}
    )
    assert r.json()["code"] == "PASSWORD_REUSED"
    r = api.post(
        "/auth/change-password", json={"current_password": password, "new_password": "pendek"}
    )
    assert r.status_code == 422

    api.ok("POST", "/auth/change-password", 204,
           json={"current_password": password, "new_password": "BaruBanget1"})  # fmt: skip
    api.ok("GET", "/auth/me")  # sesi sendiri tetap
    assert other_device.get("/auth/me").status_code == 401  # perangkat lain dicabut

    fresh = Api(target)
    fresh.login(user["email"], password, expect=401)
    fresh.login(user["email"], "BaruBanget1")
    other_device.close()
    fresh.close()
