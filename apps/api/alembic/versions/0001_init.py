"""init schema: katalog, stok, opname, akun, audit

Revision ID: 0001
Revises:
Create Date: 2026-11-17
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _run_sql_file(name: str) -> None:
    sql = (_SQL_DIR / name).read_text(encoding="utf-8")
    # Eksekusi lewat koneksi driver (psycopg) langsung: tanpa parsing bind-param SQLAlchemy,
    # sehingga ':' / '%' di dalam fungsi plpgsql aman. Tetap dalam transaksi migrasi.
    op.get_bind().connection.driver_connection.execute(sql)  # type: ignore[union-attr]


def upgrade() -> None:
    _run_sql_file("0001_init.up.sql")


def downgrade() -> None:
    _run_sql_file("0001_init.down.sql")
