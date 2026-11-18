"""waktu transaksi monoton per varian

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""

from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _run(name: str) -> None:
    sql = (_SQL_DIR / name).read_text(encoding="utf-8")
    op.get_bind().connection.driver_connection.execute(sql)  # type: ignore[union-attr]


def upgrade() -> None:
    _run("0002_monotonic_time.up.sql")


def downgrade() -> None:
    _run("0002_monotonic_time.down.sql")
