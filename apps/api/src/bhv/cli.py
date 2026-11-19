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


# Data contoh dari prototipe; semua stok awal dicatat sebagai transaksi IN (temuan #1).
_SEED: list[tuple[str, str, int | None, list[tuple[str, str | None, int, int]]]] = [
    # kategori, nama, harga, [(ukuran, warna, stok_min, stok_awal)]
    ("Kemeja", "Kemeja Batik Pria", 185000,
     [("S", None, 10, 12), ("M", None, 10, 20), ("L", None, 10, 30), ("XL", None, 10, 8)]),
    ("Blazer", "Blazer Formal Wanita", 450000, [("M", "Hitam", 8, 6), ("L", "Hitam", 8, 9)]),
    ("Celana", "Celana Bahan Pria", 220000, [("30", None, 10, 12), ("32", None, 10, 15)]),
    ("Gamis", "Gamis Brokat", 375000, [("L", "Hijau Botol", 5, 7), ("XL", "Hijau Botol", 5, 3)]),
]  # fmt: skip


@app.command()
def seed() -> None:
    """Isi data contoh (kategori, barang, varian, stok awal + 1 penjualan). Aman diulang."""
    import uuid

    with _connect() as conn:
        admin = conn.execute(
            "SELECT id FROM users WHERE role = 'admin' AND is_active ORDER BY id LIMIT 1"
        ).fetchone()
        if admin is None:
            typer.secho("Belum ada admin. Jalankan `bhv create-admin` dulu.", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        uid = admin[0]
        created = 0
        for cat, name, price, variants in _SEED:
            conn.execute("INSERT INTO categories (name) VALUES (%s) ON CONFLICT DO NOTHING", (cat,))
            cid = conn.execute("SELECT id FROM categories WHERE name = %s", (cat,)).fetchone()[0]  # type: ignore[index]
            if conn.execute(
                "SELECT 1 FROM products WHERE name = %s AND category_id = %s", (name, cid)
            ).fetchone():
                continue
            pid = conn.execute(
                "INSERT INTO products (category_id, name, price, created_by)"
                " VALUES (%s, %s, %s, %s) RETURNING id",
                (cid, name, price, uid),
            ).fetchone()[0]  # type: ignore[index]
            gid = uuid.uuid4()
            conn.execute(
                "INSERT INTO movement_groups (id, kind, request_hash, line_count, user_id)"
                " VALUES (%s, 'IN', 'seed', %s, %s)",
                (gid, len(variants), uid),
            )
            for size, color, min_stock, qty in variants:
                vid = conn.execute(
                    "INSERT INTO product_variants (product_id, size, color, min_stock)"
                    " VALUES (%s, %s, %s, %s) RETURNING id",
                    (pid, size, color, min_stock),
                ).fetchone()[0]  # type: ignore[index]
                conn.execute(
                    "INSERT INTO stock_movements (group_id, variant_id, type, qty, note, source,"
                    " user_id) VALUES (%s, %s, 'IN', %s, 'Stok awal', 'initial', %s)",
                    (gid, vid, qty, uid),
                )
            created += 1
        # contoh penjualan (seperti prototipe: 6 kemeja keluar)
        if created:
            vid = conn.execute(
                "SELECT pv.id FROM product_variants pv JOIN products p ON p.id = pv.product_id"
                " JOIN categories c ON c.id = p.category_id"
                " WHERE c.name = 'Kemeja' AND p.name = 'Kemeja Batik Pria' AND pv.size = 'L'"
            ).fetchone()
            if vid:
                gid = uuid.uuid4()
                conn.execute(
                    "INSERT INTO movement_groups (id, kind, request_hash, line_count, user_id)"
                    " VALUES (%s, 'OUT', 'seed', 1, %s)",
                    (gid, uid),
                )
                conn.execute(
                    "INSERT INTO stock_movements (group_id, variant_id, type, qty, reason, source,"
                    " user_id) VALUES (%s, %s, 'OUT', -6, 'sale', 'manual', %s)",
                    (gid, vid[0], uid),
                )
    typer.echo(f"Seed selesai: {created} barang baru.")


@app.command()
def openapi(
    out: Annotated[Path, typer.Option(help="File tujuan JSON")] = Path("openapi.json"),
) -> None:
    """Tulis skema OpenAPI (kontrak untuk frontend: `pnpm gen:api`)."""
    import json

    from bhv.main import app as api_app

    payload = json.dumps(api_app.openapi(), indent=2, ensure_ascii=False)
    out.write_text(payload + chr(10), "utf-8")
    typer.echo(f"OpenAPI ditulis ke {out}")


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
