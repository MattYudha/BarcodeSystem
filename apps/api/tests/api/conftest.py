"""E2E API lewat HTTP sungguhan.

Dua mode, tes yang sama:
- Lokal (default): uvicorn dijalankan sebagai subprocess terhadap DB test (`bhv_test`).
- Stack Docker / CI: set E2E_BASE_URL (mis. http://localhost:8000) + E2E_ADMIN_EMAIL/PASSWORD
  (admin dibuat dengan `bhv create-admin`). E2E_DATABASE_URL opsional untuk tes yang perlu
  memanipulasi waktu sesi langsung di DB.

Setiap test memakai data unik & IP palsu unik (X-Forwarded-For) agar rate-limit tidak saling ganggu.
"""

import os
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from e2e_support import ALLOWED_ORIGIN, Api, Target, unique

from bhv.integrity import libpq_url
from bhv.security import hash_password

API_DIR = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_ready(url: str, proc: subprocess.Popen[bytes] | None = None) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"API berhenti saat start (exit {proc.returncode})")
        try:
            if httpx.get(f"{url}/readyz", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"API tidak siap: {url}")


@pytest.fixture(scope="session")
def target(request: pytest.FixtureRequest) -> Iterator[Target]:
    base = os.environ.get("E2E_BASE_URL")
    if base:
        base = base.rstrip("/")
        _wait_ready(base)
        db = os.environ.get("E2E_DATABASE_URL")
        yield Target(
            base,
            os.environ["E2E_ADMIN_EMAIL"],
            os.environ["E2E_ADMIN_PASSWORD"],
            libpq_url(db) if db else None,
        )
        return

    db_url: str = request.getfixturevalue("db_url")  # DB test bersih + migrasi
    email, password = "admin@bhavia-e2e.com", "Admin-e2e-123"
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES ('Admin E2E', %s, %s,"
            " 'admin') ON CONFLICT (email) DO NOTHING",
            (email, hash_password(password)),
        )

    port = _free_port()
    sa_url = "postgresql+psycopg://" + db_url.split("://", 1)[1]
    env = {
        **os.environ,
        "DATABASE_URL": sa_url,
        "APP_ENV": "test",
        "ALLOWED_ORIGINS": ALLOWED_ORIGIN,
        "SESSION_IDLE_MINUTES": "30",
    }
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "uvicorn", "bhv.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--loop", "bhv.runtime:new_event_loop", "--proxy-headers",
         "--forwarded-allow-ips", "127.0.0.1", "--log-level", "warning"],
        cwd=API_DIR, env=env,
    )  # fmt: skip
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_ready(base, proc)
        yield Target(base, email, password, db_url)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def anon(target: Target) -> Iterator[Api]:
    api = Api(target)
    yield api
    api.close()


@pytest.fixture
def admin(target: Target) -> Iterator[Api]:
    api = Api(target)
    api.login(target.admin_email, target.admin_password)
    yield api
    api.close()


@pytest.fixture
def make_user(target: Target, admin: Api) -> Iterator[Any]:
    clients: list[Api] = []

    def _make(role: str = "staff", login: bool = True) -> tuple[Api, dict[str, Any], str]:
        password = "Rahasia-" + uuid.uuid4().hex[:8]
        user = admin.ok("POST", "/users", 201, json={
            "name": unique("Staf"), "email": f"{uuid.uuid4().hex[:10]}@bhavia-e2e.com",
            "role": role, "password": password,
        })  # fmt: skip
        api = Api(target)
        clients.append(api)
        if login:
            api.login(user["email"], password)
        return api, user, password

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def staff(make_user: Any) -> Api:
    api, _, _ = make_user("staff")
    return api


@pytest.fixture
def category(admin: Api) -> dict[str, Any]:
    return admin.ok("POST", "/categories", 201, json={"name": unique("Kemeja")})


@pytest.fixture
def pg(target: Target) -> Iterator[psycopg.Connection]:
    if not target.db_url:
        pytest.skip("butuh akses DB langsung (E2E_DATABASE_URL)")
    with psycopg.connect(target.db_url, autocommit=True) as c:
        yield c
