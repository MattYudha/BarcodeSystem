"""Alembic env: migrasi ditulis sebagai raw SQL (trigger/enum/constraint penting ada di DB)."""

from alembic import context
from sqlalchemy import create_engine, pool

from bhv.config import get_settings

config = context.config


def _url() -> str:
    # Bisa dioverride: alembic -x db_url=... upgrade head (dipakai oleh test runner)
    return context.get_x_argument(as_dictionary=True).get("db_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
