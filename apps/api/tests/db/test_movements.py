"""Pergerakan stok: aturan bisnis yang dijaga trigger & constraint."""

from contextlib import nullcontext

import psycopg
import pytest
from conftest import Db, raises_check, raises_code


@pytest.fixture
def user(db: Db) -> int:
    return db.user()


@pytest.fixture
def vid(db: Db) -> int:
    return db.variant()


def test_in_increases_stock_and_sets_balance(db: Db, user: int, vid: int) -> None:
    _, bal = db.move(vid, "IN", 30, user, note="Stok awal", source="initial")
    assert bal == 30 and db.stock(vid) == 30
    _, bal = db.move(vid, "OUT", -6, user, reason="sale")
    assert bal == 24 and db.stock(vid) == 24


def test_out_exceeding_stock_rejected_without_side_effect(db: Db, user: int, vid: int) -> None:
    db.move(vid, "IN", 5, user)
    with raises_code("INSUFFICIENT_STOCK"):
        db.move(vid, "OUT", -6, user, reason="sale")
    assert db.stock(vid) == 5
    assert db.movement_count(vid) == 1


def test_out_exactly_available_ok(db: Db, user: int, vid: int) -> None:
    db.move(vid, "IN", 5, user)
    _, bal = db.move(vid, "OUT", -5, user, reason="damaged")
    assert bal == 0 and db.stock(vid) == 0


def test_client_supplied_balance_and_time_ignored(db: Db, user: int, vid: int) -> None:
    row = db.conn.execute(
        "INSERT INTO stock_movements (variant_id, type, qty, source, user_id, balance_after, created_at)"
        " VALUES (%s, 'IN', 3, 'manual', %s, 999, '2000-01-01') RETURNING balance_after, created_at",
        (vid, user),
    ).fetchone()
    assert row is not None
    assert row[0] == 3
    assert row[1].year >= 2026


@pytest.mark.parametrize(
    ("type_", "qty", "kwargs", "constraint"),
    [
        ("IN", -1, {}, "ck_mv_in_positive"),
        ("OUT", 1, {"reason": "sale"}, "ck_mv_out_negative"),
        ("OUT", -1, {}, "ck_mv_reason_only_out"),
        ("IN", 1, {"reason": "sale"}, "ck_mv_reason_only_out"),
        ("OUT", -1, {"reason": "other"}, "ck_mv_other_needs_note"),
        (
            "OUT",
            -1,
            {"reason": "sale", "production_date": "2026-11-01"},
            "ck_mv_production_only_in",
        ),
        ("ADJUST", 1, {}, "ck_mv_adjust_needs_note"),
        ("ADJUST", 1, {"note": "   "}, "ck_mv_adjust_needs_note"),
        ("ADJUST", 1, {"note": "x", "source": "initial"}, "ck_mv_initial_is_in"),
        ("ADJUST", 1, {"note": "x", "source": "opname"}, "ck_mv_opname_link"),
    ],
)
def test_movement_constraints(
    db: Db, user: int, vid: int, type_: str, qty: int, kwargs: dict[str, str], constraint: str
) -> None:
    db.move(vid, "IN", 10, user)
    with raises_check(constraint):
        db.move(vid, type_, qty, user, **kwargs)  # type: ignore[arg-type]
    assert db.stock(vid) == 10


def test_qty_zero_rejected(db: Db, user: int, vid: int) -> None:
    with raises_check():
        db.move(vid, "ADJUST", 0, user, note="nol")


def test_adjust_with_note_both_directions(db: Db, user: int, vid: int) -> None:
    db.move(vid, "ADJUST", 7, user, note="Koreksi hitung")
    _, bal = db.move(vid, "ADJUST", -2, user, note="Koreksi hitung")
    assert bal == 5


def test_adjust_cannot_make_stock_negative(db: Db, user: int, vid: int) -> None:
    db.move(vid, "IN", 1, user)
    with raises_code("INSUFFICIENT_STOCK"):
        db.move(vid, "ADJUST", -2, user, note="x")


def test_archived_variant_blocks_in_out(db: Db, user: int, vid: int) -> None:
    db.move(vid, "IN", 3, user)
    db.conn.execute("UPDATE product_variants SET archived_at = now() WHERE id = %s", (vid,))
    with raises_code("VARIANT_ARCHIVED"):
        db.move(vid, "IN", 1, user)
    with raises_code("VARIANT_ARCHIVED"):
        db.move(vid, "OUT", -1, user, reason="sale")


def test_archived_product_blocks_in(db: Db, user: int) -> None:
    pid, _ = db.product()
    vid = db.variant(pid)
    db.conn.execute("UPDATE products SET archived_at = now() WHERE id = %s", (pid,))
    with raises_code("VARIANT_ARCHIVED"):
        db.move(vid, "IN", 1, user)


def test_unknown_variant(db: Db, user: int) -> None:
    with raises_code("VARIANT_NOT_FOUND"):
        db.move(999_999_999, "IN", 1, user)


# --- Pembatalan (reversal) -----------------------------------------------------------------


def test_reverse_out_restores_stock(db: Db, user: int, vid: int) -> None:
    db.move(vid, "IN", 10, user)
    out_id, _ = db.move(vid, "OUT", -4, user, reason="sale")
    _, bal = db.move(vid, "REVERSAL", 4, user, reversal_of=out_id, note="Salah scan")
    assert bal == 10 and db.stock(vid) == 10


def test_reverse_twice_rejected(db: Db, user: int, vid: int) -> None:
    in_id, _ = db.move(vid, "IN", 10, user)
    db.move(vid, "REVERSAL", -10, user, reversal_of=in_id, note="Salah")
    with raises_code("ALREADY_REVERSED"):
        db.move(vid, "REVERSAL", -10, user, reversal_of=in_id, note="Salah lagi")


def test_reverse_reversal_rejected(db: Db, user: int, vid: int) -> None:
    db.move(vid, "IN", 10, user)
    out_id, _ = db.move(vid, "OUT", -3, user, reason="sale")
    rev_id, _ = db.move(vid, "REVERSAL", 3, user, reversal_of=out_id, note="x")
    with raises_code("CANNOT_REVERSE_REVERSAL"):
        db.move(vid, "REVERSAL", -3, user, reversal_of=rev_id, note="x")


@pytest.mark.parametrize("qty", [-5, 3, -3])
def test_reverse_qty_must_mirror(db: Db, user: int, vid: int, qty: int) -> None:
    in_id, _ = db.move(vid, "IN", 5, user)
    db.move(vid, "IN", 5, user)
    with raises_code("REVERSAL_MISMATCH") if qty != -5 else nullcontext():
        db.move(vid, "REVERSAL", qty, user, reversal_of=in_id, note="x")


def test_reverse_wrong_variant_rejected(db: Db, user: int, vid: int) -> None:
    other = db.variant()
    in_id, _ = db.move(vid, "IN", 5, user)
    db.move(other, "IN", 5, user)
    with raises_code("REVERSAL_MISMATCH"):
        db.move(other, "REVERSAL", -5, user, reversal_of=in_id, note="x")


def test_reverse_in_after_goods_left_rejected(db: Db, user: int, vid: int) -> None:
    in_id, _ = db.move(vid, "IN", 5, user)
    db.move(vid, "OUT", -4, user, reason="sale")
    with raises_code("INSUFFICIENT_STOCK"):
        db.move(vid, "REVERSAL", -5, user, reversal_of=in_id, note="x")


def test_reversal_requires_link_and_note(db: Db, user: int, vid: int) -> None:
    in_id, _ = db.move(vid, "IN", 5, user)
    with raises_check("ck_mv_reversal_link"):
        db.move(vid, "REVERSAL", -5, user, note="x")
    with raises_check("ck_mv_reversal_needs_note"):
        db.move(vid, "REVERSAL", -5, user, reversal_of=in_id)
    with raises_check("ck_mv_reversal_link"):
        db.move(vid, "ADJUST", -5, user, reversal_of=in_id, note="x")


# --- Immutability -------------------------------------------------------------------------


def test_movements_immutable(db: Db, user: int, vid: int) -> None:
    mid, _ = db.move(vid, "IN", 5, user)
    with raises_code("IMMUTABLE_RECORD"):
        db.conn.execute("UPDATE stock_movements SET qty = 50 WHERE id = %s", (mid,))
    with raises_code("IMMUTABLE_RECORD"):
        db.conn.execute("DELETE FROM stock_movements WHERE id = %s", (mid,))
    with raises_code("IMMUTABLE_RECORD"):
        db.conn.execute("TRUNCATE stock_movements CASCADE")
    assert db.stock(vid) == 5


def test_direct_stock_write_rejected(db: Db, vid: int) -> None:
    with raises_code("STOCK_DIRECT_WRITE"):
        db.conn.execute("UPDATE product_variants SET stock = 100 WHERE id = %s", (vid,))


def test_stock_guard_is_reset_after_movement(
    db: Db, user: int, vid: int, conn: psycopg.Connection
) -> None:
    # Dalam satu transaksi: setelah movement, guard harus kembali 'off'.
    with conn.transaction():
        db.move(vid, "IN", 5, user)
        with raises_code("STOCK_DIRECT_WRITE"), conn.transaction():
            conn.execute("UPDATE product_variants SET stock = 100 WHERE id = %s", (vid,))
    assert db.stock(vid) == 5


def test_audit_logs_immutable(db: Db, user: int) -> None:
    aid = db.one(
        "INSERT INTO audit_logs (actor_id, action) VALUES (%s, 'test.action') RETURNING id", (user,)
    )
    with raises_code("IMMUTABLE_RECORD"):
        db.conn.execute("UPDATE audit_logs SET action = 'x' WHERE id = %s", (aid,))
    with raises_code("IMMUTABLE_RECORD"):
        db.conn.execute("DELETE FROM audit_logs WHERE id = %s", (aid,))
