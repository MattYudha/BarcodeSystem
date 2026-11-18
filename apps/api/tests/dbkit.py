"""Helper tes DB (nama modul unik agar tidak bentrok dengan conftest lain)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg import errors


class Db:
    """Helper pembuat data; setiap test membuat datanya sendiri (nama unik), tanpa cleanup."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def one(self, query: str, params: Any = None) -> Any:
        row = self.conn.execute(query, params).fetchone()
        assert row is not None
        return row[0] if len(row) == 1 else row

    def user(self, role: str = "staff") -> int:
        email = f"u-{uuid.uuid4().hex[:10]}@test.local"
        return int(
            self.one(
                "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, 'x', %s) RETURNING id",
                ("Tester", email, role),
            )
        )

    def category(self) -> int:
        return int(
            self.one(
                "INSERT INTO categories (name) VALUES (%s) RETURNING id",
                (f"Kat-{uuid.uuid4().hex[:8]}",),
            )
        )

    def product(self, name: str = "Kemeja Batik Pria") -> tuple[int, str]:
        row = self.one(
            "INSERT INTO products (category_id, name) VALUES (%s, %s) RETURNING id, code",
            (self.category(), name),
        )
        return int(row[0]), str(row[1])

    def variant(
        self,
        product_id: int | None = None,
        size: str = "M",
        color: str | None = None,
        min_stock: int = 0,
    ) -> int:
        if product_id is None:
            product_id, _ = self.product()
        return int(
            self.one(
                "INSERT INTO product_variants (product_id, size, color, min_stock) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (product_id, size, color, min_stock),
            )
        )

    def move(
        self,
        variant_id: int,
        type_: str,
        qty: int,
        user_id: int,
        *,
        reason: str | None = None,
        note: str | None = None,
        reversal_of: int | None = None,
        source: str = "manual",
        production_date: str | None = None,
        opname_id: int | None = None,
        conn: psycopg.Connection | None = None,
    ) -> tuple[int, int]:
        c = conn or self.conn
        row = c.execute(
            "INSERT INTO stock_movements (variant_id, type, qty, reason, note, reversal_of, source,"
            " production_date, opname_id, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " RETURNING id, balance_after",
            (
                variant_id,
                type_,
                qty,
                reason,
                note,
                reversal_of,
                source,
                production_date,
                opname_id,
                user_id,
            ),
        ).fetchone()
        assert row is not None
        return int(row[0]), int(row[1])

    def stock(self, variant_id: int) -> int:
        return int(self.one("SELECT stock FROM product_variants WHERE id = %s", (variant_id,)))

    def movement_count(self, variant_id: int) -> int:
        return int(
            self.one("SELECT count(*) FROM stock_movements WHERE variant_id = %s", (variant_id,))
        )


@contextmanager
def raises_code(code: str) -> Iterator[None]:
    """Error bisnis dari trigger: SQLSTATE P0001, MESSAGE = kode."""
    with pytest.raises(errors.RaiseException) as exc:
        yield
    assert exc.value.diag.message_primary == code, exc.value.diag.message_primary


@contextmanager
def raises_check(constraint: str | None = None) -> Iterator[None]:
    with pytest.raises(errors.CheckViolation) as exc:
        yield
    if constraint:
        assert exc.value.diag.constraint_name == constraint, exc.value.diag.constraint_name
