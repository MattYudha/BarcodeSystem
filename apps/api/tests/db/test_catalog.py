"""Katalog: kode produk, barcode varian, normalisasi & immutability."""

import re

import psycopg
import pytest
from conftest import Db, raises_check, raises_code
from psycopg import errors


def test_format_seq_does_not_truncate(db: Db) -> None:
    assert db.one("SELECT bhv_format_seq(7, 4)") == "0007"
    assert db.one("SELECT bhv_format_seq(9999, 4)") == "9999"
    assert db.one("SELECT bhv_format_seq(12345, 4)") == "12345"  # lpad biasa -> '1234'
    assert db.one("SELECT bhv_format_seq(100, 2)") == "100"


def test_product_code_is_system_generated(db: Db) -> None:
    cat = db.category()
    code = db.one(
        "INSERT INTO products (category_id, name, code) VALUES (%s, 'X', 'BHV-9999') RETURNING code",
        (cat,),
    )
    assert re.fullmatch(r"BHV-\d{4,}", code)
    assert code == db.one("SELECT 'BHV-' || bhv_format_seq(last_value, 4) FROM product_code_seq")


def test_product_codes_are_consecutive(db: Db) -> None:
    _, a = db.product()
    _, b = db.product()
    assert int(b.split("-")[1]) == int(a.split("-")[1]) + 1


def test_product_code_immutable(db: Db) -> None:
    pid, _ = db.product()
    with raises_code("IMMUTABLE_FIELD"):
        db.conn.execute("UPDATE products SET code = 'BHV-0000' WHERE id = %s", (pid,))


def test_product_name_change_keeps_barcode(db: Db) -> None:
    pid, _ = db.product()
    vid = db.variant(pid)
    before = db.one("SELECT barcode FROM product_variants WHERE id = %s", (vid,))
    db.conn.execute("UPDATE products SET name = 'Nama Baru' WHERE id = %s", (pid,))
    assert db.one("SELECT barcode FROM product_variants WHERE id = %s", (vid,)) == before


def test_variant_barcodes_sequential_per_product(db: Db) -> None:
    pid, code = db.product()
    barcodes = [
        db.one("SELECT barcode FROM product_variants WHERE id = %s", (db.variant(pid, size=s),))
        for s in ("S", "M", "L")
    ]
    assert barcodes == [f"{code}-01", f"{code}-02", f"{code}-03"]


def test_variant_barcode_ignores_client_value_and_stock(db: Db) -> None:
    pid, code = db.product()
    row = db.one(
        "INSERT INTO product_variants (product_id, size, barcode, variant_no, stock)"
        " VALUES (%s, 'XL', 'BHV-0001-77', 77, 500) RETURNING barcode, variant_no, stock",
        (pid,),
    )
    assert row == (f"{code}-01", 1, 0)


def test_variant_suffix_widens_past_99(db: Db) -> None:
    pid, code = db.product()
    db.conn.execute("UPDATE products SET next_variant_no = 100 WHERE id = %s", (pid,))
    vid = db.variant(pid)
    assert db.one("SELECT barcode FROM product_variants WHERE id = %s", (vid,)) == f"{code}-100"


def test_next_variant_no_cannot_go_back(db: Db) -> None:
    pid, _ = db.product()
    db.variant(pid)
    with raises_code("IMMUTABLE_FIELD"):
        db.conn.execute("UPDATE products SET next_variant_no = 1 WHERE id = %s", (pid,))


def test_barcode_immutable(db: Db) -> None:
    vid = db.variant()
    with raises_code("IMMUTABLE_FIELD"):
        db.conn.execute("UPDATE product_variants SET barcode = 'BHV-0001-99' WHERE id = %s", (vid,))


@pytest.mark.parametrize("color", [None, "Merah"])
def test_duplicate_size_color_rejected(db: Db, color: str | None) -> None:
    pid, _ = db.product()
    db.variant(pid, size="M", color=color)
    with pytest.raises(errors.UniqueViolation):
        db.variant(pid, size="M", color=color)


def test_duplicate_color_case_insensitive(db: Db) -> None:
    pid, _ = db.product()
    db.variant(pid, size="M", color="Merah")
    with pytest.raises(errors.UniqueViolation):
        db.variant(pid, size="M", color="merah")


def test_same_size_different_color_ok(db: Db) -> None:
    pid, _ = db.product()
    db.variant(pid, size="M", color="Merah")
    db.variant(pid, size="M", color="Biru")
    db.variant(pid, size="M", color=None)


@pytest.mark.parametrize(("size", "color"), [("m", None), (" M", None), ("M", " Merah"), ("M", "")])
def test_variant_normalization_enforced(db: Db, size: str, color: str | None) -> None:
    with raises_check():
        db.variant(size=size, color=color)


def test_archived_product_cannot_get_variants(db: Db) -> None:
    pid, _ = db.product()
    db.conn.execute("UPDATE products SET archived_at = now() WHERE id = %s", (pid,))
    with raises_code("PRODUCT_ARCHIVED"):
        db.variant(pid)


def test_variant_with_movements_cannot_be_deleted(db: Db) -> None:
    user = db.user()
    vid = db.variant()
    db.move(vid, "IN", 5, user, note="Stok awal", source="initial")
    with pytest.raises(errors.ForeignKeyViolation):
        db.conn.execute("DELETE FROM product_variants WHERE id = %s", (vid,))


def test_variant_without_movements_can_be_deleted(db: Db) -> None:
    vid = db.variant()
    db.conn.execute("DELETE FROM product_variants WHERE id = %s", (vid,))


def test_negative_price_and_min_stock_rejected(db: Db) -> None:
    with raises_check():
        db.conn.execute(
            "INSERT INTO products (category_id, name, price) VALUES (%s, 'X', -1)", (db.category(),)
        )
    with raises_check():
        db.variant(min_stock=-1)


def test_category_name_unique_case_insensitive(db: Db) -> None:
    name = f"Kemeja-{db.one('SELECT gen_random_uuid()::text')[:6]}"
    db.conn.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
    with pytest.raises(errors.UniqueViolation):
        db.conn.execute("INSERT INTO categories (name) VALUES (%s)", (name.upper(),))


def test_user_email_unique_case_insensitive(db: Db, conn: psycopg.Connection) -> None:
    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES ('A', 'Admin.X@Bhavia.id', 'h')"
    )
    with pytest.raises(errors.UniqueViolation):
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES ('B', 'admin.x@bhavia.id', 'h')"
        )


def test_view_stock_status(db: Db) -> None:
    user = db.user()
    pid, _ = db.product()
    v_out = db.variant(pid, size="S", min_stock=0)
    v_low = db.variant(pid, size="M", min_stock=5)
    v_ok = db.variant(pid, size="L", min_stock=5)
    db.move(v_low, "IN", 5, user)
    db.move(v_ok, "IN", 6, user)
    rows = dict(
        (r[0], (r[1], r[2]))
        for r in db.conn.execute(
            "SELECT variant_id, stock_status, is_alert FROM v_variant_stock WHERE product_id = %s",
            (pid,),
        ).fetchall()
    )
    assert rows[v_out] == ("out", False)  # min_stock 0 -> tidak masuk alert
    assert rows[v_low] == ("low", True)  # stok <= minimum
    assert rows[v_ok] == ("ok", False)
