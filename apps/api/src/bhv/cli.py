"""CLI operasional: `uv run bhv --help`."""

import os
from pathlib import Path

import psycopg
import typer

from bhv.config import get_settings
from bhv.integrity import find_stock_issues, libpq_url

app = typer.Typer(help="Bhavia Inventory — perintah operasional", no_args_is_help=True)

# Lokasi alembic.ini: env BHV_API_DIR (image Docker) atau folder apps/api saat development.
_API_DIR = Path(os.environ.get("BHV_API_DIR") or Path(__file__).resolve().parents[2])


@app.command()
def migrate(revision: str = "head") -> None:
    """Jalankan migrasi database (alembic upgrade)."""
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(_API_DIR / "alembic.ini")), revision)
    typer.echo(f"Migrasi selesai ({revision}).")


@app.command("check-stock")
def check_stock() -> None:
    """Rekonsiliasi: stok cache = Σ transaksi = saldo terakhir, saldo berjalan konsisten."""
    with psycopg.connect(libpq_url(get_settings().database_url)) as conn:
        issues = find_stock_issues(conn)
    if not issues:
        typer.secho("OK - semua stok konsisten.", fg=typer.colors.GREEN)
        return
    for issue in issues:
        typer.secho(f"[{issue.kind}] {issue.detail}", fg=typer.colors.RED)
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
