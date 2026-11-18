"""Fixture test: DB Postgres asli (bukan SQLite) karena logika stok ada di trigger/constraint."""

import argparse
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from dbkit import Db
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from bhv.config import get_settings
from bhv.integrity import libpq_url

API_DIR = Path(__file__).resolve().parents[1]


def _alembic(sa_url: str, action: str, revision: str) -> None:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.cmd_opts = argparse.Namespace(x=[f"db_url={sa_url}"])
    getattr(command, action)(cfg, revision)


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    sa_url = get_settings().test_database_url
    url = libpq_url(sa_url)
    dbname = conninfo_to_dict(url)["dbname"]
    assert dbname and "test" in str(dbname), "TEST_DATABASE_URL harus menunjuk DB khusus test"

    admin = make_conninfo(url, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname)))
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))

    # upgrade -> downgrade -> upgrade: memastikan migrasi bisa dibalik.
    _alembic(sa_url, "upgrade", "head")
    _alembic(sa_url, "downgrade", "base")
    _alembic(sa_url, "upgrade", "head")
    yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(db_url, autocommit=True) as c:
        yield c


@pytest.fixture
def db(conn: psycopg.Connection) -> Db:
    return Db(conn)
