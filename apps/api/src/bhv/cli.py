"""CLI operasional: `uv run bhv --help`."""

import os
from pathlib import Path
from typing import Annotated

import psycopg
import typer

from bhv.config import get_settings
from bhv.integrity import find_stock_issues, libpq_url
from bhv.security import MIN_PASSWORD_LENGTH, hash_password

app = typer.Typer(help="Bhavia Inventory - perintah operasional", no_args_is_help=True)

# Lokasi alembic.ini: env BHV_API_DIR (image Docker) atau folder apps/api saat development.
_API_DIR = Path(os.environ.get("BHV_API_DIR") or Path(__file__).resolve().parents[2])


def _connect() -> psycopg.Connection:
    return psycopg.connect(libpq_url(get_settings().database_url))


@app.command()
def migrate(revision: str = "head") -> None:
    """Jalankan migrasi database (alembic upgrade)."""
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(_API_DIR / "alembic.ini")), revision)
    typer.echo(f"Migrasi selesai ({revision}).")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: Annotated[bool, typer.Option(help="Auto-reload untuk development")] = False,
) -> None:
    """Jalankan API (SelectorEventLoop agar psycopg async jalan juga di Windows)."""
    import uvicorn

    uvicorn.run(
        "bhv.main:app",
        host=host,
        port=port,
        reload=reload,
        loop="bhv.runtime:new_event_loop",
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


@app.command("create-admin")
def create_admin(
    email: Annotated[str, typer.Option(prompt=True)],
    name: Annotated[str, typer.Option(prompt=True)] = "Admin",
    password: Annotated[
        str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)
    ] = "",
) -> None:
    """Buat akun admin pertama (atau jadikan akun yang ada admin aktif + set password)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        typer.secho(f"Password minimal {MIN_PASSWORD_LENGTH} karakter.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    with _connect() as conn:
        row = conn.execute(
            """
            INSERT INTO users (name, email, password_hash, role)
            VALUES (%s, lower(%s), %s, 'admin')
            ON CONFLICT (email) DO UPDATE
               SET role = 'admin', is_active = TRUE, password_hash = EXCLUDED.password_hash,
                   must_change_password = FALSE, password_changed_at = now()
            RETURNING id, (xmax = 0) AS inserted
            """,
            (name.strip(), email.strip(), hash_password(password)),
        ).fetchone()
        assert row is not None
        conn.execute(
            "INSERT INTO audit_logs (actor_id, action, entity_type, entity_id)"
            " VALUES (NULL, 'cli.create_admin', 'user', %s)",
            (row[0],),
        )
    typer.echo(f"Admin {'dibuat' if row[1] else 'diperbarui'}: {email} (id {row[0]})")


@app.command("check-stock")
def check_stock() -> None:
    """Rekonsiliasi: stok cache = Σ transaksi = saldo terakhir, saldo berjalan konsisten."""
    with _connect() as conn:
        issues = find_stock_issues(conn)
    if not issues:
        typer.secho("OK - semua stok konsisten.", fg=typer.colors.GREEN)
        return
    for issue in issues:
        typer.secho(f"[{issue.kind}] {issue.detail}", fg=typer.colors.RED)
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
