"""CLI `bhv seed` & `bhv check-stock` dijalankan sebagai proses nyata terhadap DB test."""

import os
import subprocess
import sys

from dbkit import Db

from bhv.integrity import find_stock_issues


def _bhv(db_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://" + db_url.split("://", 1)[1]}
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "bhv.cli", *args], env=env, capture_output=True, text=True,
        timeout=120, check=False,
    )  # fmt: skip


def test_seed_is_idempotent_and_traceable(db: Db, db_url: str) -> None:
    db.user("admin")
    first = _bhv(db_url, "seed")
    assert first.returncode == 0, first.stderr
    again = _bhv(db_url, "seed")
    assert again.returncode == 0 and "0 barang baru" in again.stdout

    row = db.one(
        "SELECT pv.stock, (SELECT count(*) FROM stock_movements m WHERE m.variant_id = pv.id)"
        " FROM product_variants pv JOIN products p ON p.id = pv.product_id"
        " JOIN categories c ON c.id = p.category_id"
        " WHERE c.name = 'Kemeja' AND p.name = 'Kemeja Batik Pria' AND pv.size = 'L'"
    )
    assert row == (24, 2)  # stok awal 30 (IN) - 6 terjual (OUT), seperti prototipe
    # temuan #1: tidak ada stok tanpa transaksi
    assert (
        db.one(
            "SELECT count(*) FROM product_variants pv WHERE pv.stock > 0 AND NOT EXISTS"
            " (SELECT 1 FROM stock_movements m WHERE m.variant_id = pv.id)"
        )
        == 0
    )
    assert find_stock_issues(db.conn) == []
    check = _bhv(db_url, "check-stock")
    assert check.returncode == 0 and "konsisten" in check.stdout
