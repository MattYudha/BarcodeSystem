"""Konkurensi & invariant: stok tidak pernah negatif dan selalu bisa ditelusuri dari transaksi."""

import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg
from dbkit import Db
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from psycopg import errors

from bhv.integrity import find_stock_issues


def test_parallel_out_never_oversells(db: Db, db_url: str) -> None:
    user = db.user()
    vid = db.variant()
    db.move(vid, "IN", 10, user, note="Stok awal", source="initial")

    n = 20
    barrier = threading.Barrier(n)

    def take_one(_: int) -> bool:
        with psycopg.connect(db_url, autocommit=True) as c:
            barrier.wait()
            try:
                db.move(vid, "OUT", -1, user, reason="sale", conn=c)
                return True
            except errors.RaiseException as e:
                assert e.diag.message_primary == "INSUFFICIENT_STOCK"
                return False

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(take_one, range(n)))

    assert sum(results) == 10
    assert db.stock(vid) == 0
    assert find_stock_issues(db.conn) == []


def test_parallel_mixed_in_out_keeps_running_balance(db: Db, db_url: str) -> None:
    user = db.user()
    vid = db.variant()
    db.move(vid, "IN", 5, user)

    def worker(i: int) -> None:
        with psycopg.connect(db_url, autocommit=True) as c:
            for j in range(10):
                try:
                    if (i + j) % 3 == 0:
                        db.move(vid, "IN", 2, user, conn=c)
                    else:
                        db.move(vid, "OUT", -1, user, reason="sale", conn=c)
                except errors.RaiseException as e:
                    assert e.diag.message_primary == "INSUFFICIENT_STOCK"

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(8)))

    total = db.one(
        "SELECT coalesce(sum(qty), 0) FROM stock_movements WHERE variant_id = %s", (vid,)
    )
    assert db.stock(vid) == total >= 0
    assert find_stock_issues(db.conn) == []


def test_cart_in_one_transaction_is_atomic(db: Db, conn: psycopg.Connection) -> None:
    """Keranjang: jika satu baris gagal, seluruh keranjang batal."""
    user = db.user()
    a, b = db.variant(), db.variant()
    db.move(b, "IN", 1, user)
    try:
        with conn.transaction():
            db.move(a, "IN", 5, user)
            db.move(b, "OUT", -2, user, reason="sale")  # gagal: stok b = 1
    except errors.RaiseException:
        pass
    assert db.stock(a) == 0 and db.movement_count(a) == 0
    assert db.stock(b) == 1


_ops = st.lists(
    st.tuples(
        st.sampled_from(["IN", "OUT", "ADJUST", "REVERSAL"]),
        st.integers(min_value=1, max_value=8),
        st.booleans(),
    ),
    min_size=1,
    max_size=25,
)


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(ops=_ops)
def test_random_operation_sequences_keep_invariants(
    db: Db, ops: list[tuple[str, int, bool]]
) -> None:
    user = db.user()
    vid = db.variant()
    model = 0
    reversible: list[tuple[int, int]] = []  # (movement_id, qty)

    for kind, n, flag in ops:
        try:
            if kind == "IN":
                mid, _ = db.move(vid, "IN", n, user)
                reversible.append((mid, n))
                model += n
            elif kind == "OUT":
                mid, _ = db.move(vid, "OUT", -n, user, reason="sale")
                reversible.append((mid, -n))
                model -= n
            elif kind == "ADJUST":
                qty = n if flag else -n
                mid, _ = db.move(vid, "ADJUST", qty, user, note="opname")
                reversible.append((mid, qty))
                model += qty
            elif reversible:
                mid, qty = reversible.pop(n % len(reversible))
                db.move(vid, "REVERSAL", -qty, user, reversal_of=mid, note="batal")
                model -= qty
        except errors.RaiseException as e:
            assert e.diag.message_primary == "INSUFFICIENT_STOCK"
            # model tidak berubah: transaksi ditolak tanpa efek samping
        assert model >= 0
        assert db.stock(vid) == model

    assert find_stock_issues(db.conn) == []
