"""Stock opname: satu draft aktif, terkunci setelah final, ADJUST terhubung ke opname."""

import pytest
from dbkit import Db, raises_code
from psycopg import errors


def _new_opname(db: Db, user: int) -> int:
    # Tutup draft yang mungkin tertinggal dari test lain (hanya boleh satu draft).
    db.conn.execute(
        "UPDATE stock_opnames SET status = 'cancelled', cancelled_at = now() WHERE status = 'draft'"
    )
    return int(db.one("INSERT INTO stock_opnames (created_by) VALUES (%s) RETURNING id", (user,)))


def test_only_one_draft(db: Db) -> None:
    user = db.user("admin")
    _new_opname(db, user)
    with pytest.raises(errors.UniqueViolation):
        db.conn.execute("INSERT INTO stock_opnames (created_by) VALUES (%s)", (user,))


def test_opname_code_format(db: Db) -> None:
    user = db.user("admin")
    oid = _new_opname(db, user)
    assert db.one("SELECT code FROM stock_opnames WHERE id = %s", (oid,)).startswith("SO-")


def test_finalize_flow_and_lock(db: Db) -> None:
    admin = db.user("admin")
    vid = db.variant()
    db.move(vid, "IN", 10, admin)
    oid = _new_opname(db, admin)

    db.conn.execute(
        "INSERT INTO stock_opname_items (opname_id, variant_id, counted_qty, counted_by)"
        " VALUES (%s, %s, 7, %s)",
        (oid, vid, admin),
    )
    with db.conn.transaction():
        db.conn.execute(
            "UPDATE stock_opname_items SET system_qty = 10, diff = -3 WHERE opname_id = %s", (oid,)
        )
        db.move(vid, "ADJUST", -3, admin, note="Stock opname", source="opname", opname_id=oid)
        db.conn.execute(
            "UPDATE stock_opnames SET status = 'finalized', finalized_at = now(), finalized_by = %s"
            " WHERE id = %s",
            (admin, oid),
        )
    assert db.stock(vid) == 7

    with raises_code("OPNAME_CLOSED"):
        db.conn.execute(
            "UPDATE stock_opname_items SET counted_qty = 1 WHERE opname_id = %s", (oid,)
        )
    with raises_code("OPNAME_CLOSED"):
        db.conn.execute("UPDATE stock_opnames SET note = 'x' WHERE id = %s", (oid,))
    with raises_code("IMMUTABLE_RECORD"):
        db.conn.execute("DELETE FROM stock_opnames WHERE id = %s", (oid,))


def test_diff_must_match(db: Db) -> None:
    admin = db.user("admin")
    vid = db.variant()
    oid = _new_opname(db, admin)
    with pytest.raises(errors.CheckViolation):
        db.conn.execute(
            "INSERT INTO stock_opname_items (opname_id, variant_id, counted_qty, system_qty, diff,"
            " counted_by) VALUES (%s, %s, 5, 3, 1, %s)",
            (oid, vid, admin),
        )


def test_status_fields_consistent(db: Db) -> None:
    admin = db.user("admin")
    oid = _new_opname(db, admin)
    with pytest.raises(errors.CheckViolation):
        db.conn.execute("UPDATE stock_opnames SET status = 'finalized' WHERE id = %s", (oid,))
