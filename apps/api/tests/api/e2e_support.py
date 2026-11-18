"""Helper E2E API (dipakai conftest & tes). Lihat conftest.py untuk mode lokal vs stack."""

import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

ALLOWED_ORIGIN = os.environ.get("E2E_ALLOWED_ORIGIN", "http://localhost:3000")
PREFIX = "/api/v1"


@dataclass
class Target:
    base_url: str
    admin_email: str
    admin_password: str
    db_url: str | None


def _fake_ip() -> str:
    n = uuid.uuid4().int
    return f"10.{n % 250}.{(n >> 8) % 250}.{(n >> 16) % 250 + 1}"


class Api:
    """Klien HTTP dengan cookie jar & IP palsu sendiri (seolah perangkat berbeda)."""

    def __init__(self, target: Target, ip: str | None = None) -> None:
        self.target = target
        self.ip = ip or _fake_ip()
        self.http = httpx.Client(
            base_url=target.base_url + PREFIX,
            headers={"X-Forwarded-For": self.ip, "X-Device-Id": str(uuid.uuid4())},
            timeout=20,
        )
        self.me: dict[str, Any] | None = None

    def login(self, email: str, password: str, expect: int = 200) -> httpx.Response:
        r = self.http.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == expect, r.text
        if r.status_code == 200:
            self.me = r.json()
        return r

    def get(self, url: str, **kw: Any) -> httpx.Response:
        return self.http.get(url, **kw)

    def post(self, url: str, **kw: Any) -> httpx.Response:
        return self.http.post(url, **kw)

    def patch(self, url: str, **kw: Any) -> httpx.Response:
        return self.http.patch(url, **kw)

    def delete(self, url: str, **kw: Any) -> httpx.Response:
        return self.http.delete(url, **kw)

    def ok(self, method: str, url: str, expect: int = 200, **kw: Any) -> Any:
        r = self.http.request(method, url, **kw)
        assert r.status_code == expect, f"{method} {url} -> {r.status_code}: {r.text}"
        if r.status_code == 204 or not r.content:
            return None
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return r

    def close(self) -> None:
        self.http.close()


def unique(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def create_product(admin: Api, category_id: int, **overrides: Any) -> dict[str, Any]:
    body = {
        "category_id": category_id,
        "name": unique("Kemeja Batik Pria"),
        "price": 185000,
        "variants": [
            {"size": "M", "color": "Merah", "min_stock": 5, "initial_stock": 10},
            {"size": "L", "color": "Merah", "min_stock": 5, "initial_stock": 3},
            {"size": "XL", "min_stock": 0, "initial_stock": 0},
        ],
    }
    body.update(overrides)
    return admin.ok("POST", "/products", 201, json=body)
